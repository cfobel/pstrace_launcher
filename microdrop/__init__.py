"""
Copyright 2013 Christian Fobel

This file is part of dmf_control_board.

pstrace_launcher is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

pstrace_launcher is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with pstrace_launcher.  If not, see <http://www.gnu.org/licenses/>.
"""
import os
from datetime import datetime
from subprocess import check_call
from logger import logger
from flatland import Boolean, Form
from pygtkhelpers.ui.extra_widgets import Filepath
from pygtkhelpers.ui.form_view_dialog import FormViewDialog
from plugin_helpers import AppDataController, StepOptionsController
from plugin_manager import (IPlugin, Plugin, implements,
                            PluginGlobals, ScheduleRequest, emit_signal)
from app_context import get_app
import gtk
from path import path
import psutil


def safe_psutil_attr(process, attr):
    '''
    Since some attributes do not apply to all processes, this function attempts
    to retrieve the specified attribute, but returns `None` in the case where
    an exception of any kind occurs.
    '''
    try:
        value = getattr(process, attr)
    except:
        value = None
    return value


class PSTraceOptions():
    """
    This class stores the options for a single step in the protocol.
    """
    def __init__(self, run_pstrace=None, script=None):
        self.run_pstrace = run_pstrace
        self.script = script


PluginGlobals.push_env('microdrop.managed')

class PSTraceLauncher(Plugin, AppDataController, StepOptionsController):
    """
    This class is automatically registered with the PluginManager.
    """
    implements(IPlugin)
    #version = get_plugin_version(path(__file__).parent.parent)
    version = '0.1'
    plugins_name = 'wheelerlab.pstrace_launcher'

    AppFields = Form.of(Filepath.named('pstrace_exe').using(default='',
                                                            optional=True))

    StepFields = Form.of(Boolean.named('run_pstrace').using(default=False,
                                                            optional=True))

    def __init__(self):
        self.name = self.plugins_name
        self.initialized = False

    def on_plugin_enable(self):
        """
        Handler called once the plugin instance has been enabled.
        """
        app = get_app()

        if not self.initialized:
            self.pstrace_launcher_menu_item = gtk.MenuItem('PSTrace step '
                                                           'config...')
            app.main_window_controller.menu_tools.append(
                    self.pstrace_launcher_menu_item)
            self.pstrace_launcher_menu_item.connect("activate",
                                                    self.on_select_script)
            self.initialized = True
        self.pstrace_launcher_menu_item.show()
        super(PSTraceLauncher, self).on_plugin_enable()

    def on_plugin_disable(self):
        """
        Handler called once the plugin instance has been disabled.
        """
        self.pstrace_launcher_menu_item.hide()

    def on_select_script(self, widget, data=None):
        """
        Handler called when the user clicks on
        "PSTrace step config..." in the "Tools" menu.
        """
        app = get_app()
        options = self.get_step_options()
        form = Form.of(Filepath.named('script').using(default=options.script,
                                                      optional=True))
        dialog = FormViewDialog()
        valid, response =  dialog.run(form)

        step_options_changed = False
        if valid and (response['script'] and response['script'] !=
                      options.script):
            options.script = response['script']
            step_options_changed = True
        if step_options_changed:
            emit_signal('on_step_options_changed', [self.name,
                                                    app.protocol
                                                    .current_step_number],
                        interface=IPlugin)

    def on_step_run(self):
        # `get_step_options` is provided by the `StepOptionsController` mixin.
        options = self.get_step_options()
        app_values = self.get_app_values()
        if options.run_pstrace and options.script:
            exe_path = path(app_values['pstrace_exe'])
            script = path(options.script)
            if not exe_path.isfile():
                logger.error('[PSTraceLauncher] invalid exe-path: %s' %
                             exe_path.abspath())
            elif not script.isfile():
                logger.error('[PSTraceLauncher] invalid script-path: %s' %
                             script.abspath())
            elif os.name != 'nt':
                logger.error('[PSTraceLauncher] This plugin is only supported '
                             'on Windows')
            else:
                command = ['start', '/d', exe_path.parent.abspath(),
                           exe_path.name, script.abspath()]
                pstrace_processes = [p for p in psutil.process_iter() if
                                     safe_psutil_attr(p, 'exe') ==
                                     exe_path.abspath()]
                if not pstrace_processes:
                    logger.info('[PSTraceLauncher] execute: %s', command)
                    check_call(command, shell=True)
                else:
                    logger.info('[PSTraceLauncher] skipping, since PSTrace is '
                                'already running as process %s',
                                [p.pid for p in pstrace_processes])
        self.complete_step()

    def complete_step(self, return_value=None):
        app = get_app()
        if app.running or app.realtime_mode:
            emit_signal('on_step_complete', [self.name, return_value])

    def get_default_options(self):
        return PSTraceOptions()

    def get_step(self, default):
        if default is None:
            return get_app().protocol.current_step_number
        return default

    def get_step_options(self, step_number=None):
        """
        Return a ODSensorOptions object for the current step in the protocol.
        If none exists yet, create a new one.
        """
        step_number = self.get_step(step_number)
        app = get_app()
        step = app.protocol.steps[step_number]
        options = step.get_data(self.name)
        if options is None:
            # No data is registered for this plugin (for this step).
            options = self.get_default_options()
            step.set_data(self.name, options)
        return options

    def get_schedule_requests(self, function_name):
        """
        Returns a list of scheduling requests (i.e., ScheduleRequest
        instances) for the function specified by function_name.
        """
        # We need to run before the Abbott plugin, since the Abbott plugin
        # blocks while waiting for the user to manually click 'OK' after the
        # _Photo-Multiplier-Tube (PMT)_ reading has been taken.  By requesting
        # to be scheduled before the Abbott plugin, we can launch our script
        # as a _non-blocking_ call, allowing our program to overlap execution
        # with the Abbott PMT program.
        if function_name in ['on_step_run']:
            return [ScheduleRequest(self.name, 'abbott.immunoassay')]
        return []

    def get_step_values(self, step_number=None):
        step_number = self.get_step(step_number)
        options = self.get_step_options(step_number)
        values = {}
        for name in self.StepFields.field_schema_mapping:
            value = getattr(options, name)
            values[name] = value
        return values

    def get_step_value(self, name, step_number=None):
        app = get_app()
        if not name in self.StepFields.field_schema_mapping:
            raise KeyError('No field with name %s for plugin %s' % (name,
                                                                    self.name))
        if step_number is None:
            step_number = app.protocol.current_step_number
        step = app.protocol.steps[step_number]

        options = step.get_data(self.name)
        if options is None:
            return None
        return getattr(options, name)

    def set_step_values(self, values_dict, step_number=None):
        step_number = self.get_step(step_number)
        el = self.StepFields(value=values_dict)
        try:
            if not el.validate():
                raise ValueError()
            options = self.get_step_options(step_number=step_number)
            for name, field in el.iteritems():
                if field.value is None:
                    continue
                else:
                    setattr(options, name, field.value)
        finally:
            emit_signal('on_step_options_changed', [self.name, step_number],
                    interface=IPlugin)

    def on_step_options_changed(self, plugin, step_number):
        app = get_app()
        if not app.running and (app.realtime_mode and plugin == self.name and
                                app.protocol.current_step_number ==
                                step_number):
            logger.debug('[PSTraceLauncher] on_step_options_changed(): %s step'
                         '%d' % (plugin, step_number))
            #self.on_step_run()


PluginGlobals.pop_env()
