#!/usr/bin/env python3
"""
ignite.py: turn a cloud-config configuration into an Ignition configuration that will install the real cloud-config and execute it.
"""

# Contains code from the Toil project: https://github.com/DataBiosphere/toil/blob/e505923067dbdb362258740ae4c1eda4e27d8708/src/toil/provisioners/abstractProvisioner.py

# Copyright (C) 2015-2022 Regents of the University of California
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import textwrap
import json

from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import quote

class InstanceConfiguration:
    """
    Allows defining the initial setup for an instance and then turning it
    into an Ignition configuration for instance user data.
    """

    def __init__(self):
        # Holds dicts with keys 'path', 'owner', 'permissions', and 'content' for files to create.
        # Permissions is a string octal number with leading 0.
        self.files = []
        # Holds dicts with keys 'name', 'command', and 'content' defining Systemd units to create
        self.units = []
        # Holds strings like "ssh-rsa actualKeyData" for keys to authorize (independently of cloud provider's system)
        self.sshPublicKeys = []

    def addFile(self, path: str, filesystem: str = 'root', mode: Union[str, int] = '0755', contents: str = '', append: bool = False):
        """
        Make a file on the instance with the given filesystem, mode, and contents.
        See the storage.files section:
        https://github.com/kinvolk/ignition/blob/flatcar-master/doc/configuration-v2_2.md
        """
        if isinstance(mode, str):
            # Convert mode from octal to decimal
            mode = int(mode, 8)
        assert isinstance(mode, int)

        contents = 'data:,' + quote(contents.encode('utf-8'))

        ignition_file = {'path': path, 'filesystem': filesystem, 'mode': mode, 'contents': {'source': contents}}

        if append:
            ignition_file["append"] = append

        self.files.append(ignition_file)

    def addUnit(self, name: str, enabled: bool = True, contents: str = ''):
        """
        Make a systemd unit on the instance with the given name (including
        .service), and content. Units will be enabled by default.
        Unit logs can be investigated with:
            systemctl status whatever.service
        or:
            journalctl -xe
        """

        self.units.append({'name': name, 'enabled': enabled, 'contents': contents})

    def addSSHRSAKey(self, keyData: str):
        """
        Authorize the given bare, encoded RSA key (without "ssh-rsa").
        """

        self.sshPublicKeys.append("ssh-rsa " + keyData)

    def toIgnitionConfig(self) -> str:
        """
        Return an Ignition configuration describing the desired config.
        """

        # Define the base config.  We're using Flatcar's v2.2.0 fork
        # See: https://github.com/kinvolk/ignition/blob/flatcar-master/doc/configuration-v2_2.md
        config = {
            'ignition': {
                'version': '2.2.0'
            },
            'storage': {
                'files': self.files
            },
            'systemd': {
                'units': self.units
            }
        }

        if len(self.sshPublicKeys) > 0:
            # Add SSH keys if needed
            config['passwd'] = {
                'users': [
                    {
                        'name': 'core',
                        'sshAuthorizedKeys': self.sshPublicKeys
                    }
                ]
            }

        # Serialize as JSON
        return json.dumps(config, separators=(',', ':'))
        
if __name__ == "__main__":
    cloud_init_config = sys.stdin.read()
    
    config = InstanceConfiguration()
    
    config.addFile('/etc/cloud/cloud.cfg', mode='0644', contents=cloud_init_config)
    config.addFile('/opt/cloud-init/install.sh', contents=textwrap.dedent("""\
    #!/usr/bin/env bash
    set -x
    cd /run/cloud-init
    wget https://launchpad.net/cloud-init/trunk/22.4/+download/cloud-init-22.4.tar.gz
    tar -xvzf cloud-init-22.4.tar.gz
    cd cloud-init-22.4
    python setup.py install
    systemctl start cloud-init-local.service
    systemctl start cloud-init.service
    systemctl --no-block start cloud-config.service
    systemctl --no-block start cloud-final.service
    """))
    config.addUnit('install-and-run-cloud-init.service', contents=textwrap.dedent("""\
    [Unit]
    Description=Install and run cloud-init
    After=network-online.target
    Wants=network-online.target
    [Service]
    Type=oneshot
    ExecStart=/opt/cloud-init/install.sh
    RemainAfterExit=yes
    TimeoutSec=0
    StandardOutput=journal+console
    [Install]
    WantedBy=multi-user.target
    """))
    print(config.toIgnitionConfig())
    
