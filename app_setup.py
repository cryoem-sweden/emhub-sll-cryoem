# **************************************************************************
# *
# * Authors:     J.M. De la Rosa Trevin (delarosatrevin@scilifelab.se) [1]
# *
# * [1] SciLifeLab, Stockholm University
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
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
# *  e-mail address 'delarosatrevin@scilifelab.se'
# *
# **************************************************************************

"""
Instance-extension hook for the SLL customization (loaded by core's
load_module('app_setup') in emhub/__init__.py, after app.dm is created).

Currently this just wires up the SciLifeLab Order Portal integration:
if the instance's config.py defines SLL_PORTAL_API, build a PortalManager
and attach it to the Flask app as app.sll_pm, exactly as core used to do
inline before this code (and the PortalManager/PortalData classes) moved
here on 2026-09-22 (see README.rst, section 5). When SLL_PORTAL_API is not
set (e.g. local/dev instances without access to the Portal), app.sll_pm is
simply never set, same as before - callers that use it already either
guard with hasattr(app, 'sll_pm') (dc_reports.py) or are only reachable
from pages that require it (Invoice Periods).
"""

import os
import importlib.util


def _load_sibling_module(name):
    """ Load a .py file next to this one by explicit file path, the same
    way core's own load_module() loads extension files - this avoids
    needing to put this directory on sys.path just to import a sibling
    module. """
    module_path = os.path.join(os.path.dirname(__file__), name + '.py')
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_app(app):
    portalAPI = app.config.get('SLL_PORTAL_API', None)
    if portalAPI is not None:
        portal = _load_sibling_module('portal')
        app.sll_pm = portal.PortalManager(portalAPI, cache=False)
        print("SLL extension: PortalManager configured (app.sll_pm).")
