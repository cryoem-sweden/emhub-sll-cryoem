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
load_module('api') in emhub/__init__.py, via extend_api(api_bp), before
the api blueprint is registered).

Moved here from core (emhub/blueprints/api.py) on 2026-09-22: importing
an Application from the SciLifeLab Order Portal only makes sense on this
instance (it needs app.sll_pm, see app_setup.py / portal.py in this repo),
and nothing else in core or any other instance customization used it.
"""

import traceback

import flask_login
from flask import request
from flask import current_app as app

from emhub.utils import datetime_from_isoformat, send_json_data, send_error


def extend_api(api_bp):

    @api_bp.route('/import_application', methods=['POST'])
    @flask_login.login_required
    def import_application():
        try:
            if not request.is_json:
                raise Exception("Expecting JSON request.")

            orderCode = request.json['code'].upper()

            dm = app.dm

            application = dm.get_application_by(code=orderCode)

            if application is not None:
                raise Exception('Application %s already exist' % orderCode)

            orderJson = app.sll_pm.fetchOrderDetailsJson(orderCode)

            if orderJson is None:
                raise Exception('Invalid application ID %s' % orderCode)

            piEmail = orderJson['owner']['email'].lower()
            # orderId = orderJson['identifier']

            pi = dm.get_user_by(email=piEmail)

            if pi is None:
                raise Exception("Order owner email (%s) not found as PI" % piEmail)

            if orderJson['status'] not in ['accepted', 'processing']:
                raise Exception("Only applications with status 'accepted' or "
                                "'processing' can be imported. ")

            fields = orderJson['fields']
            description = fields.get('project_des', None)
            invoiceRef = fields.get('project_invoice_addess', None)

            created = datetime_from_isoformat(orderJson['created'])
            pi_list = fields.get('pi_list', [])

            form = orderJson['form']
            iuid = form['iuid']

            # Check if the given form (here templates) already exist
            # or we need to create a new one
            orderTemplate = None
            templates = dm.get_templates()
            for t in templates:
                if t.extra.get('portal_iuid', None) == iuid:
                    orderTemplate = t
                    break

            if orderTemplate is None:
                orderTemplate = dm.create_template(
                    title=form['title'],
                    status='active',
                    extra={'portal_iuid': iuid}
                )
                dm.commit()

            application = dm.create_application(
                code=orderCode,
                title=orderJson['title'],
                created=created,  # datetime_from_isoformat(o['created']),
                status='active',
                description=description,
                creator_id=pi.id,
                template_id=orderTemplate.id,
                invoice_reference=invoiceRef or 'MISSING_INVOICE_REF',
            )

            for piTuple in pi_list:
                piEmail = piTuple[1].lower()
                pi = dm.get_user_by(email=piEmail)
                if pi is not None:
                    application.users.append(pi)

            dm.commit()

            return send_json_data({'application': application.json()})

        except Exception as e:
            print(e)
            traceback.print_exc()

            return send_error('ERROR from Server: %s' % e)
