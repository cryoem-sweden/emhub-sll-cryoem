#!/usr/bin/env python
# **************************************************************************
# *
# * Authors:     J.M. De la Rosa Trevin
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 2 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'delarosatrevin@gmail.com'
# *
# **************************************************************************

"""
Fix "config:*" forms that are missing from the SLL instance.

Context
-------
The SLL instance's DB (emhub.sqlite) predates the "config:" naming
convention used by current EMhub core. A DB inspection (2026-09-21) showed
it only has: sample, experiment, sessions_config (legacy, unused by
current code), processing (legacy, unused), universities (still used,
untouched), config:projects and config:bookings.

It is completely missing: config:permissions, config:sessions,
config:reports, config:users and config:resources. Current core code
reads several of these with bare dict access (no .get default), e.g.:

    emhub/data/content/dc_projects.py:
        project_perms = dm.get_config("permissions")['projects']   # KeyError: 'projects'
    emhub/data/data_manager.py (get_user_group):
        user_groups = self.get_config('sessions')['groups']        # KeyError: 'groups'
    emhub/data/content/dc_reports.py (report_microscopes_usage):
        report_resources = dm.get_config('reports')['resources']   # KeyError: 'resources'
    emhub/data/data_manager.py (check_resource_access):
        perms.get(permissionKey, {}).items()  # empty when config:permissions is
        entirely missing -> non-managers can create/delete NO bookings at all.

This script creates the missing config forms with values reconstructed
from the live SLL data (resources.tags/name, users.roles) and from Jose's
own 2024-12-12 SLL dev export (forms-sll-dev-20241212.json), which already
had most of these correctly filled in for this instance (currency, extra
roles, reports resource list, and permissions.projects). It also updates
config:bookings to attach the existing "experiment" form to each
microscope so the "Experiment" dialog (currently unusable - "There is no
Experiment form defined for this Instrument") works.

IMPORTANT - things this script deliberately does NOT invent:
  * config:sessions.acquisition is created with one EMPTY dict per
    microscope (Solna Krios alpha/beta, Talos, Umea Krios, Umea Glacios).
    This is enough to stop the KeyError when creating a Session (the
    Python-level `sconfig['acquisition'][micName]` lookup succeeds), but
    the real per-microscope acquisition defaults (voltage, magnification,
    pixel_size, dose, cs) are facility hardware data this script does not
    know and are left for you to fill in via update_config('sessions', ...)
    once you have them, otherwise the "create session" dialog will just
    show those fields blank (not crash).
  * create_booking/delete_booking permissions only cover resources tagged
    "microscope", "instrument" or "service" (9 of the 15 current
    resources). Chamaleon (tags="Cham"), Umea Aquilos 2
    (tags="Umea cryo-FIB-SEM"), Mass Photometry (tags="Refeyn"), and
    Rapid Support Data Processing / Primo (no tags) don't match any of
    those and will stay manager-only to book until they get a matching
    tag or an explicit permissions entry - please confirm if that's
    intentional.

Run with the emhub server for the SLL instance up locally and the usual
SLL client env vars sourced (EMHUB_SERVER_URL, EMHUB_USER, EMHUB_PASSWORD),
e.g.:

    source /Users/jdela80/work/data/instances/sll/bashrc
    python /Users/jdela80/work/development/emhub-otf/emhub-extras/emhub-sll-cryoem/scripts/20260921_fix_sll_missing_configs.py

The script is idempotent for the forms it *creates*: if you run it again
after a config already exists, it will just update() it in place with the
same definition below (edit the constants and re-run any time you need to
push a change).
"""

import json

from emtools.utils import Pretty, Color
from emhub.client import open_client


# ---------------------------------------------------------------------------
# New config forms (currently entirely missing from the SLL DB)
# ---------------------------------------------------------------------------

CONFIG_PERMISSIONS = {
    "create_booking": {
        "microscope": ["admin", "manager", "user"],
        "instrument": ["admin", "manager", "user"],
        "service": ["admin", "manager", "user"]
    },
    "delete_booking": {
        "microscope": ["admin", "manager", "user"],
        "instrument": ["admin", "manager", "user"],
        "service": ["admin", "manager", "user"]
    },
    "create_session": ["manager", "admin"],
    "content": {
        "usage_report": ["admin", "manager", "head"],
        "raw": ["admin"]
    },
    # This is the key that was missing and causing:
    #   KeyError: 'projects' in dc_projects.py/get_user_projects
    "projects": {
        "can_create": "all",
        "view_options": [
            {"key": "mine", "label": "My Projects"},
            {"key": "lab", "label": "Lab's Projects"},
            {"key": "all", "label": "All Projects"}
        ]
    }
}

CONFIG_SESSIONS = {
    # Used (bare access) by DataManager.get_user_group():
    #   user_groups = self.get_config('sessions')['groups']
    "groups": {},
    # Used (bare access) by dc_sessions.py/session_content() when creating
    # a Session from a Booking:
    #   acq = sconfig['acquisition'][micName]
    # Empty dicts avoid the KeyError; fill in real values per microscope
    # (voltage, magnification, pixel_size, dose, cs) when you have them.
    "acquisition": {
        "Solna Krios α": {},
        "Solna Krios β": {},
        "Talos": {},
        "Umeå Krios": {},
        "Umeå Glacios": {}
    }
}

CONFIG_REPORTS = {
    # From forms-sll-dev-20241212.json, and matches current resource names.
    "resources": ["Solna Krios α", "Solna Krios β", "Talos"],
    "microscope_usage": {}
}

CONFIG_USERS = {
    # Matches the "staff-solna" / "staff-umea" roles already used by real
    # users in the DB (users.roles), and forms-sll-dev-20241212.json.
    "extra_roles": ["staff-solna", "staff-umea"]
}

CONFIG_RESOURCES = {
    # From forms-sll-dev-20241212.json.
    "currency": "SEK"
}

NEW_CONFIGS = {
    "config:permissions": CONFIG_PERMISSIONS,
    "config:sessions": CONFIG_SESSIONS,
    "config:reports": CONFIG_REPORTS,
    "config:users": CONFIG_USERS,
    "config:resources": CONFIG_RESOURCES,
}

# ---------------------------------------------------------------------------
# Existing config forms that need extra data
# ---------------------------------------------------------------------------

# Resources currently tagged as microscopes (dm.get_resources() / resource.tags)
MICROSCOPE_RESOURCE_NAMES = [
    "Solna Krios α",
    "Solna Krios β",
    "Talos",
    "Umeå Krios",
    "Umeå Glacios",
]


def log(message):
    print(f"{Pretty.now()}: {message}", flush=True)


def update_configs():
    with open_client() as dc:
        forms = {f['name']: f for f in dc.request('get_forms', jsonData=None).json()}

        log(Color.green(">>> Creating missing config forms..."))
        for name, definition in NEW_CONFIGS.items():
            if name in forms:
                log(Color.warn(f"     - {name} already exists, updating it in place"))
                form = forms[name]
                form['definition'] = definition
                dc.request('update_form', jsonData={'attrs': form})
            else:
                log(Color.bold(f"     - Creating {name}..."))
                formData = {'name': name, 'definition': definition}
                dc.request('create_form', jsonData={'attrs': formData}).json()

        log(Color.green(">>> Updating config:bookings with experiment_forms..."))
        bookings_form = forms.get('config:bookings')
        if bookings_form is None:
            log(Color.warn("     - config:bookings not found, skipping"))
        else:
            definition = dict(bookings_form['definition'])  # keep existing 'display', etc.
            definition['experiment_forms'] = {
                name: 'experiment' for name in MICROSCOPE_RESOURCE_NAMES
            }
            bookings_form['definition'] = definition
            dc.request('update_form', jsonData={'attrs': bookings_form})
            log(f"     Done. experiment_forms -> {json.dumps(definition['experiment_forms'])}")

        log(Color.green(">>> Done."))


def main():
    update_configs()


if __name__ == '__main__':
    main()
