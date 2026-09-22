# **************************************************************************
# *
# * Authors:     J.M. De la Rosa Trevin (delarosatrevin@scilifelab.se) [1]
# *              Grigory Sharov (gsharov@mrc-lmb.cam.ac.uk) [2]
# *
# * [1] SciLifeLab, Stockholm University
# * [2] MRC Laboratory of Molecular Biology (MRC-LMB)
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
Register content functions related to the SciLifeLab Order Portal
integration (app.sll_pm, see portal.py / app_setup.py in this repo).

Moved here from core's emhub/data/content/dc_base.py on 2026-09-22 (see
README.rst, section 6). Fixed at the same time: these three content
functions were defined but never registered with @dc.content (dc.content
stores by function name, and the names here didn't even match the
content_id values the templates request), and they referenced an
undefined `self` (these are plain functions nested in register_content(),
not methods) - so this whole "Import Users / Import Applications from
Portal" admin feature was unreachable before this fix.

Also overrides core's `create_session_form` content function (see
README.rst, section 7): register_content() runs after core's own content
registration (core's dc_sessions.register_content(dc) happens at import
time via emhub/data/content/__init__.py; this module is only loaded and
called later, from create_app()), so re-registering the same function
name here with @dc.content replaces core's version in dc._contentDict -
same mechanism the paired create_session_form.html template override in
this repo's templates/ relies on (extra/templates is searched before
core's templates, see emhub/__init__.py).
"""
import os
import datetime as dt

import flask

from emtools.utils import Pretty
from emhub.utils import datetime_from_isoformat


def register_content(dc):

    def _get_users_from_portal(status=None):
        """ Retrieve users from Portal with a given status.
        If status is None, all will be retrieved.
        """
        dm = dc.app.dm
        users = []

        for pu in dc.app.sll_pm.fetchAccountsJson():
            user = dm.get_user_by(email=pu['email'])

            if user is None:
                invoiceRef = pu['invoice_ref']

                if pu['status'] == 'enabled':
                    pu['pi_user'] = None

                    if not pu['pi']:
                        pi = dm.get_user_by(email=invoiceRef)
                        if pi is None:
                            pu['status'] = 'error: Missing PI'
                        else:
                            pu['status'] = 'ready: user'
                            pu['pi_user'] = pi
                    else:
                        if invoiceRef.strip():
                            pu['status'] = 'ready: pi'
                        else:
                            pu['status'] = 'error: Missing Invoice Reference'

                    if status is None or pu['status'].startswith(status):
                        users.append(pu)

        return users

    @dc.content
    def portal_users_list(**kwargs):
        dm = dc.app.dm
        do_import = 'import' in kwargs
        imported = []
        failed = []

        if do_import:
            users = _get_users_from_portal(status='ready')
            for u in users:
                roles = ['user', 'pi'] if u['pi'] else ['user']
                pi_id = None if u['pi'] else u['pi_user'].id

                try:
                    user = dm.create_user(
                        username=u['email'],
                        email=u['email'],
                        phone='',
                        password=os.urandom(24).hex(),
                        name="%(first_name)s %(last_name)s" % u,
                        roles=roles,
                        pi_id=pi_id,
                        status='active'
                    )
                    imported.append(u)

                    if dc.app.mm:
                        dc.app.mm.send_mail(
                            [user.email],
                            "emhub: New account imported",
                            flask.render_template('email/account_created.txt',
                                                  user=user))
                except Exception as e:
                    u['error'] = str(e)
                    failed.append(u)
            status = None
        else:
            status = kwargs.get('status', None)

        users = _get_users_from_portal(status)

        return {'portal_users': users,
                'status': status,
                'do_import': do_import,
                'users_imported': imported,
                'users_failed': failed
                }

    @dc.content
    def portal_import_application(**kwargs):
        # Date since the created orders in the portal will be considered
        sinceArg = kwargs.get('since', None)

        if sinceArg:
            since = datetime_from_isoformat(sinceArg)
        else:
            since = dc.app.dm.now() - dt.timedelta(days=183)  # 6 months

        result = {'since': since}

        ordersJson = dc.app.sll_pm.fetchOrdersJson()

        def _filter(o):
            s = o['status']
            code = o['identifier'].upper()
            application = dc.app.dm.get_application_by(code=code)
            o['app'] = application.id if application else 'None'
            modified = datetime_from_isoformat(o['modified'])

            return ((s == 'accepted' or s == 'processing')
                    and application is None and modified >= since)

        result['orders'] = [o for o in ordersJson if _filter(o)]

        return result

    @dc.content
    def applications_check(**kwargs):
        dm = dc.app.dm

        sinceArg = kwargs.get('since', None)

        if sinceArg:
            since = datetime_from_isoformat(sinceArg)
        else:
            since = dc.app.dm.now() - dt.timedelta(days=183)  # 6 months
        results = {}

        accountsJson = dc.app.sll_pm.fetchAccountsJson()
        usersDict = {a['email'].lower(): a for a in accountsJson}

        for application in dm.get_applications():
            app_results = {}
            errors = []

            if application.created < since:
                continue

            orderCode = application.code.upper()
            orderJson = dc.app.sll_pm.fetchOrderDetailsJson(orderCode)

            if orderJson is None:
                errors.append('Invalid application ID %s' % orderCode)
            else:
                fields = orderJson['fields']
                pi_list = fields.get('pi_list', [])
                pi_missing = []

                for piTuple in pi_list:
                    piName, piEmail = piTuple
                    piEmail = piEmail.lower()

                    pi = dm.get_user_by(email=piEmail)
                    piInfo = ''
                    if pi is None:
                        if piEmail in usersDict:
                            piInfo = "in the portal, pi: %s" % usersDict[piEmail]['pi']
                        else:
                            piInfo = "NOT in the portal"

                    else:
                        if pi.id != application.creator.id and pi not in application.users:
                            piInfo = 'NOT in APP'
                    if piInfo:
                        pi_missing.append((piName, piEmail, piInfo))

                if pi_missing:
                    app_results['pi_missing'] = pi_missing

            if errors:
                app_results['errors'] = errors

            if app_results:
                app_results['application'] = application
                results[orderCode] = app_results

        return {'checks': results,
                'since': since
                }

    @dc.content
    def create_session_form(**kwargs):
        """ Override of core's create_session_form
        (emhub/data/content/dc_sessions.py). Identical to core except it
        also computes 'suggested_session_name' - a read-only preview of
        the SLL auto-numbered code (cem/dbb/fac/ext + counter, see
        DataManager.get_new_session_info(), README.rst section 7) that
        will be assigned if the operator leaves the Session Name field
        blank. This is a pure read (get_new_session_info() does not
        consume/increment the counter - only an actual
        DataManager.create_session() call does), so it's safe to compute
        on every render of this form, including if the operator opens it
        more than once without creating a session.
        """
        dm = dc.app.dm
        user = dc.app.user
        booking_id = int(kwargs['booking_id'])
        b = dm.get_booking_by(id=booking_id)
        can_edit = b.project and user.can_edit_project(b.project)

        if not (user.is_manager or user.same_pi(b.owner) or can_edit):
            raise Exception("You can not create Sessions for this Booking. "
                            "Only members of the same lab can do it.")

        sconfig = dm.get_config('sessions')

        # load default acquisition params for the given microscope
        micName = b.resource.name
        acq = sconfig['acquisition'][micName]
        dateStr = Pretty.date(b.start).replace('-', '')

        session_info = dm.get_new_session_info(booking_id)

        data = {
            'booking': b,
            'acquisition': acq,
            'session_name_prefix': f'{dateStr}{b.resource.name}:',
            'suggested_session_name': session_info['name'],
            'session_extra_form': dm.get_session_form(b.resource.name)
        }
        data.update(dc.get_user_projects(b.owner, status='active'))
        return data
