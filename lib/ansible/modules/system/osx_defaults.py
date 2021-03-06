#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2014, GeekChimp - Franck Nijhof <franck@geekchimp.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['stableinterface'],
                    'supported_by': 'community'}

DOCUMENTATION = r'''
---
module: osx_defaults
author:
- Franck Nijhof (@frenck)
short_description: Manage macOS user defaults
description:
  - osx_defaults allows users to read, write, and delete macOS user defaults from Ansible scripts.
  - macOS applications and other programs use the defaults system to record user preferences and other
    information that must be maintained when the applications are not running (such as default font for new
    documents, or the position of an Info panel).
version_added: "2.0"
options:
  domain:
    description:
      - The domain is a domain name of the form C(com.companyname.appname).
    type: str
    default: NSGlobalDomain
  host:
    description:
      - The host on which the preference should apply.
      - The special value C(currentHost) corresponds to the C(-currentHost) switch of the defaults commandline tool.
    type: str
    version_added: "2.1"
  key:
    description:
      - The key of the user preference.
    type: str
    required: true
  type:
    description:
      - The type of value to write.
    type: str
    choices: [ array, bool, boolean, date, float, int, integer, string ]
    default: string
  array_add:
    description:
      - Add new elements to the array for a key which has an array as its value.
    type: bool
    default: no
  value:
    description:
      - The value to write.
      - Only required when C(state=present).
    type: raw
  state:
    description:
      - The state of the user defaults.
    type: str
    choices: [ absent, present ]
    default: present
  path:
    description:
      - The path in which to search for C(osx_defaults).
    type: str
    default: /usr/bin:/usr/local/bin
notes:
    - Apple Mac caches defaults. You may need to logout and login to apply the changes.
'''

EXAMPLES = r'''
- osx_defaults:
    domain: com.apple.Safari
    key: IncludeInternalDebugMenu
    type: bool
    value: true
    state: present

- osx_defaults:
    domain: NSGlobalDomain
    key: AppleMeasurementUnits
    type: str
    value: Centimeters
    state: present

- osx_defaults:
    domain: com.apple.screensaver
    host: currentHost
    key: showClock
    type: int
    value: 1

- osx_defaults:
    key: AppleMeasurementUnits
    type: str
    value: Centimeters

- osx_defaults:
    key: AppleLanguages
    type: array
    value:
      - en
      - nl

- osx_defaults:
    domain: com.geekchimp.macable
    key: ExampleKeyToRemove
    state: absent
'''

import datetime
import re

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.six import binary_type, text_type


# exceptions --------------------------------------------------------------- {{{
class OSXDefaultsException(Exception):
    pass


# /exceptions -------------------------------------------------------------- }}}

# class MacDefaults -------------------------------------------------------- {{{
class OSXDefaults(object):
    """ Class to manage Mac OS user defaults """

    # init ---------------------------------------------------------------- {{{
    """ Initialize this module. Finds 'defaults' executable and preps the parameters """

    def __init__(self, **kwargs):

        # Initial var for storing current defaults value
        self.current_value = None

        # Just set all given parameters
        for key, val in kwargs.items():
            setattr(self, key, val)

        # Try to find the defaults executable
        self.executable = self.module.get_bin_path(
            'defaults',
            required=False,
            opt_dirs=self.path.split(':'),
        )

        if not self.executable:
            raise OSXDefaultsException("Unable to locate defaults executable.")

        # When state is present, we require a parameter
        if self.state == "present" and self.value is None:
            raise OSXDefaultsException("Missing value parameter")

        # Ensure the value is the correct type
        self.value = self._convert_type(self.type, self.value)

    # /init --------------------------------------------------------------- }}}

    # tools --------------------------------------------------------------- {{{
    """ Converts value to given type """

    def _convert_type(self, type, value):

        if type == "string":
            return str(value)
        elif type in ["bool", "boolean"]:
            if isinstance(value, (binary_type, text_type)):
                value = value.lower()
            if value in [True, 1, "true", "1", "yes"]:
                return True
            elif value in [False, 0, "false", "0", "no"]:
                return False
            raise OSXDefaultsException("Invalid boolean value: {0}".format(repr(value)))
        elif type == "date":
            try:
                return datetime.datetime.strptime(value.split("+")[0].strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise OSXDefaultsException(
                    "Invalid date value: {0}. Required format yyy-mm-dd hh:mm:ss.".format(repr(value))
                )
        elif type in ["int", "integer"]:
            if not str(value).isdigit():
                raise OSXDefaultsException("Invalid integer value: {0}".format(repr(value)))
            return int(value)
        elif type == "float":
            try:
                value = float(value)
            except ValueError:
                raise OSXDefaultsException("Invalid float value: {0}".format(repr(value)))
            return value
        elif type == "array":
            if not isinstance(value, list):
                raise OSXDefaultsException("Invalid value. Expected value to be an array")
            return value

        raise OSXDefaultsException('Type is not supported: {0}'.format(type))

    """ Returns a normalized list of commandline arguments based on the "host" attribute """

    def _host_args(self):
        if self.host is None:
            return []
        elif self.host == 'currentHost':
            return ['-currentHost']
        else:
            return ['-host', self.host]

    """ Returns a list containing the "defaults" executable and any common base arguments """

    def _base_command(self):
        return [self.executable] + self._host_args()

    """ Converts array output from defaults to an list """

    @staticmethod
    def _convert_defaults_str_to_list(value):

        # Split output of defaults. Every line contains a value
        value = value.splitlines()

        # Remove first and last item, those are not actual values
        value.pop(0)
        value.pop(-1)

        # Remove extra spaces and comma (,) at the end of values
        value = [re.sub(',$', '', x.strip(' ')) for x in value]

        return value

    # /tools -------------------------------------------------------------- }}}

    # commands ------------------------------------------------------------ {{{
    """ Reads value of this domain & key from defaults """

    def read(self):
        # First try to find out the type
        rc, out, err = self.module.run_command(self._base_command() + ["read-type", self.domain, self.key])

        # If RC is 1, the key does not exist
        if rc == 1:
            return None

        # If the RC is not 0, then terrible happened! Ooooh nooo!
        if rc != 0:
            raise OSXDefaultsException("An error occurred while reading key type from defaults: " + out)

        # Ok, lets parse the type from output
        type = out.strip().replace('Type is ', '')

        # Now get the current value
        rc, out, err = self.module.run_command(self._base_command() + ["read", self.domain, self.key])

        # Strip output
        out = out.strip()

        # An non zero RC at this point is kinda strange...
        if rc != 0:
            raise OSXDefaultsException("An error occurred while reading key value from defaults: " + out)

        # Convert string to list when type is array
        if type == "array":
            out = self._convert_defaults_str_to_list(out)

        # Store the current_value
        self.current_value = self._convert_type(type, out)

    """ Writes value to this domain & key to defaults """

    def write(self):

        # We need to convert some values so the defaults commandline understands it
        if isinstance(self.value, bool):
            if self.value:
                value = "TRUE"
            else:
                value = "FALSE"
        elif isinstance(self.value, (int, float)):
            value = str(self.value)
        elif self.array_add and self.current_value is not None:
            value = list(set(self.value) - set(self.current_value))
        elif isinstance(self.value, datetime.datetime):
            value = self.value.strftime('%Y-%m-%d %H:%M:%S')
        else:
            value = self.value

        # When the type is array and array_add is enabled, morph the type :)
        if self.type == "array" and self.array_add:
            self.type = "array-add"

        # All values should be a list, for easy passing it to the command
        if not isinstance(value, list):
            value = [value]

        rc, out, err = self.module.run_command(self._base_command() + ['write', self.domain, self.key, '-' + self.type] + value)

        if rc != 0:
            raise OSXDefaultsException('An error occurred while writing value to defaults: ' + out)

    """ Deletes defaults key from domain """

    def delete(self):
        rc, out, err = self.module.run_command(self._base_command() + ['delete', self.domain, self.key])
        if rc != 0:
            raise OSXDefaultsException("An error occurred while deleting key from defaults: " + out)

    # /commands ----------------------------------------------------------- }}}

    # run ----------------------------------------------------------------- {{{
    """ Does the magic! :) """

    def run(self):

        # Get the current value from defaults
        self.read()

        # Handle absent state
        if self.state == "absent":
            if self.current_value is None:
                return False
            if self.module.check_mode:
                return True
            self.delete()
            return True

        # There is a type mismatch! Given type does not match the type in defaults
        value_type = type(self.value)
        if self.current_value is not None and not isinstance(self.current_value, value_type):
            raise OSXDefaultsException("Type mismatch. Type in defaults: " + type(self.current_value).__name__)

        # Current value matches the given value. Nothing need to be done. Arrays need extra care
        if self.type == "array" and self.current_value is not None and not self.array_add and \
                        set(self.current_value) == set(self.value):
            return False
        elif self.type == "array" and self.current_value is not None and self.array_add and len(list(set(self.value) - set(self.current_value))) == 0:
            return False
        elif self.current_value == self.value:
            return False

        if self.module.check_mode:
            return True

        # Change/Create/Set given key/value for domain in defaults
        self.write()
        return True

        # /run ---------------------------------------------------------------- }}}


# /class MacDefaults ------------------------------------------------------ }}}


# main -------------------------------------------------------------------- {{{
def main():
    module = AnsibleModule(
        argument_spec=dict(
            domain=dict(type='str', default='NSGlobalDomain'),
            host=dict(type='str'),
            key=dict(type='str'),
            type=dict(type='str', default='string', choices=['array', 'bool', 'boolean', 'date', 'float', 'int', 'integer', 'string']),
            array_add=dict(type='bool', default=False),
            value=dict(type='raw'),
            state=dict(type='str', default='present', choices=['absent', 'present']),
            path=dict(type='str', default='/usr/bin:/usr/local/bin'),
        ),
        supports_check_mode=True,
    )

    domain = module.params['domain']
    host = module.params['host']
    key = module.params['key']
    type = module.params['type']
    array_add = module.params['array_add']
    value = module.params['value']
    state = module.params['state']
    path = module.params['path']

    try:
        defaults = OSXDefaults(module=module, domain=domain, host=host, key=key, type=type,
                               array_add=array_add, value=value, state=state, path=path)
        changed = defaults.run()
        module.exit_json(changed=changed)
    except OSXDefaultsException as e:
        module.fail_json(msg=e.message)


# /main ------------------------------------------------------------------- }}}

if __name__ == '__main__':
    main()
