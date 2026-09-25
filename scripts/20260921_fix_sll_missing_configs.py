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

(2026-09-22 update) Also merges a config:sessions.create_session mapping
in, pointing each microscope at the "create_session_form" content used by
DataManager.get_create_session_template(). Without it, the "New Session"
button on the dashboard (templates/dashboard_right.html) rendered with no
3rd JS argument, so clicking it called createSession(bookingId,
totalSessions) with create_session_func == undefined, which made the POST
to /get_content arrive with no content_id at all ->
KeyError: 'content_id' in emhub/__init__.py's get_content(). This update
is a MERGE, not a replace: it only sets the create_session key and leaves
any acquisition/groups values you've already filled in untouched.

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

 # Umeå Aquilos 2: staff only (confirmed by Umeå/Erin 2026-09-23).

CONFIG_PERMISSIONS = {
    "create_booking": {
        "microscope": ["admin", "manager", "user"],
        "instrument": ["admin", "manager", "user"],
        "service": ["admin", "manager", "user"],
        "fibsem umea": ["admin", "manager"]
    },
    "delete_booking": {
        "microscope": ["admin", "manager", "user"],
        "instrument": ["admin", "manager", "user"],
        "service": ["admin", "manager", "user"],
        "fibsem umea": ["admin", "manager"]
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
    # Used (bare access) by dc_sessions.py/create_session_form() when
    # creating a Session from a Booking:
    #   acq = sconfig['acquisition'][micName]
    # Empty dicts avoid the KeyError; fill in real values per microscope
    # (voltage, magnification, pixel_size, dose, cs) when you have them.
    "acquisition": {
        "Solna Krios α": {"voltage": 300, "magnification": 130000, "pixel_size": 0.65,  "dose": 1.0, "cs": 2.7},
        "Solna Krios β": {"voltage": 300, "magnification": 130000, "pixel_size": 0.648, "dose": 1.0, "cs": 2.7},
        "Talos":         {"voltage": 200, "magnification": 100000, "pixel_size": 1.2,   "dose": 1.0, "cs": 2.7},
        "Umeå Krios":    {"voltage": 300, "magnification": 130000, "pixel_size": 0.65,  "dose": 1.0, "cs": 2.7},
        "Umeå Glacios":  {"voltage": 200, "magnification": 100000, "pixel_size": 1.2,   "dose": 1.0, "cs": 2.7}
    }
}

# Used (bare access) by DataManager.get_create_session_template(), which
# feeds resource_create_session in dc_base.py/dashboard() and is what the
# "New Session" button's 3rd JS argument comes from. "create_session_form"
# is the existing @dc.content function/template (dc_sessions.py) that
# actually builds the session-creation dialog.
SESSIONS_CREATE_SESSION = {
    name: {"template": "create_session_form"}
    for name in [
        "Solna Krios α",
        "Solna Krios β",
        "Talos",
        "Umeå Krios",
        "Umeå Glacios",
    ]
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
    "config:reports": CONFIG_REPORTS,
    "config:users": CONFIG_USERS,
    "config:resources": CONFIG_RESOURCES,
}
# config:sessions is handled separately by update_sessions_create_session()
# below (a merge, not a blind replace like the ones above).

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


def update_sessions_create_session(dc, forms):
    """ Merge SESSIONS_CREATE_SESSION into config:sessions.create_session
    without touching any other key (in particular 'acquisition', in case
    real per-microscope values have already been filled in by hand). """
    log(Color.green(">>> Merging config:sessions.create_session..."))
    form = forms.get('config:sessions')

    if form is None:
        log(Color.bold("     - config:sessions doesn't exist yet, creating it"))
        definition = dict(CONFIG_SESSIONS)
        definition['create_session'] = SESSIONS_CREATE_SESSION
        formData = {'name': 'config:sessions', 'definition': definition}
        dc.request('create_form', jsonData={'attrs': formData})
        return

    definition = dict(form['definition'])
    definition.setdefault('groups', {})
    definition.setdefault('acquisition', dict(CONFIG_SESSIONS['acquisition']))
    definition['create_session'] = SESSIONS_CREATE_SESSION
    form['definition'] = definition
    dc.request('update_form', jsonData={'attrs': form})
    log(f"     Done. create_session -> {json.dumps(SESSIONS_CREATE_SESSION)}")


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

        update_sessions_create_session(dc, forms)

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
