=================================
EMhub SLL instance: upgrade plan
=================================

.. note::

   This doc tracks the broader plan for bringing the SLL instance up to
   date with current EMhub core, not just one crashing form. Add new
   sections here as more gaps/upgrades are found, instead of creating
   separate one-off docs.

Context
=======

The SLL instance (``/Users/jdela80/work/data/instances/sll``) runs an early
version of EMhub whose DB predates several conventions used by current core
(``~/work/development/emhub-otf/emhub``), most visibly the ``config:``-prefixed
form naming used for ``DataManager.get_config()``. This doc is the running
plan for closing those gaps, instance-specific (not upstream code changes).

Repo layout referenced below:

- Core: ``~/work/development/emhub-otf/emhub``
- SLL customization (this repo): ``~/work/development/emhub-otf/emhub-extras/emhub-sll-cryoem``
- SLL instance data: ``~/work/data/instances/sll`` (``emhub.sqlite``, ``extra`` ->
  symlinked to this repo)

The fix script referenced throughout this doc lives in this repo under
``scripts/20260921_fix_sll_missing_configs.py``.

1. Missing ``config:*`` forms (found 2026-09-21)
=================================================

Problem
-------

Several config forms current core code reads with bare dict access (no
``.get`` default) were never created for this instance. First surfaced by::

    KeyError: 'projects'
      ... dc_projects.py:46 projects_list -> get_user_projects
      ... dc_base.py:617 project_perms = dm.get_config("permissions")['projects']

Checked every backup (``backups/emhub.sqlite-backup*``, back to March 2026,
and ``emhub.sqlite-borked20250829``) - the gap is not a recent regression,
these forms have never existed in the SLL production DB.

Forms present in the live DB: ``sample``, ``experiment``, ``sessions_config``
(legacy, see section 2), ``processing`` (legacy/unused), ``universities``
(still actively used - untouched), ``config:projects``, ``config:bookings``.

Forms that were **missing**: ``config:permissions``, ``config:sessions``,
``config:reports``, ``config:users``, ``config:resources``.

Impact found while investigating (not just the reported traceback)
--------------------------------------------------------------------

- ``config:permissions`` missing entirely means ``check_resource_access()``
  denies **create/delete booking to every non-manager user** (empty dict ->
  no tag ever matches). Only managers could book instruments.
- ``config:sessions`` missing means ``get_user_group()`` (User Groups admin
  page) and ``session_content()`` ("New Session" from a booking) both crash
  with ``KeyError``.
- ``config:reports`` missing means both Reports pages
  (``report_microscopes_usage``, ``report_pis_usage``) crash with
  ``KeyError: 'resources'``.
- ``config:bookings`` exists but had no ``experiment_forms``, so the
  "Experiment" dialog always failed with "There is no Experiment form
  defined for this Instrument" even though a generic ``experiment`` form
  already exists.

Fix
---

Script (follows the existing ``emhub/client/scripts/YYYYMMDD_*.py``
convention, uses ``open_client()`` / the REST API so the Redis config cache
and validation stay consistent):

``scripts/20260921_fix_sll_missing_configs.py`` (in this repo)

Run it against the SLL instance's running server::

    source /Users/jdela80/work/data/instances/sll/bashrc
    python /Users/jdela80/work/development/emhub-otf/emhub-extras/emhub-sll-cryoem/scripts/20260921_fix_sll_missing_configs.py

Values were reconstructed from live SLL data (resource tags/names, user
roles) plus Jose's own ``forms-sll-dev-20241212.json`` dev export found in
the instance folder, which already had correct ``currency: SEK``,
``extra_roles: [staff-solna, staff-umea]``, and the reports resource list
for this instance.

Status / open items
--------------------

#. ``config:sessions.acquisition`` was created with an *empty* dict per
   microscope (Solna Krios α/β, Talos, Umeå Krios, Umeå Glacios) - just
   enough to stop the KeyError. Real voltage/magnification/pixel_size/dose/cs
   per microscope still need to be filled in (see section 2 below for where
   old camera info lives) via ``dm.update_config('sessions', ...)``.
#. **Booking permissions gap** for 5 resources not covered by the new
   ``config:permissions`` - see section 3.

2. Converting legacy ``sessions_config`` to ``config:sessions``
=================================================================

``sessions_config`` is a pre-rename form (no ``config:`` prefix).
``DataManager.get_config('sessions')`` only ever looks up
``config:sessions`` - but that's not the whole story: core reads
``sessions_config`` directly, by literal form name, from several other
``DataManager`` methods (``get_session_counter``, ``update_session_counter``,
``get_session_cameras``, ``get_session_folders``,
``get_session_data_deletion`` - see ``emhub/data/data_manager.py``).

.. warning::

   **Correction (2026-09-22):** this section originally called the
   ``counters`` sub-section below "dead data...likely safe to delete".
   That was wrong - see section 7, which investigated where session
   unique codes (``cem00734_00044``, ``dbb01967``, ...) come from and
   found that ``counters`` is live, load-bearing state read and written
   on every session creation. Do **not** delete ``sessions_config`` (or
   its ``counters`` section) - see section 7 for what actually breaks if
   you do. The ``cameras`` section below is still just informational, as
   originally described.

It has two sections worth knowing about:

.. code-block:: json

    {
      "title": "Form used as Config for Sessions",
      "sections": [
        {"label": "cameras", "params": [
            {"id": "1", "label": "Krios alpha", "enum": {"choices": ["K3", "Falcon3", "Ceta"]}},
            {"id": "2", "label": "Krios beta",  "enum": {"choices": ["K3", "Ceta-D"]}},
            {"id": "3", "label": "Talos",       "enum": {"choices": ["Falcon4i", "Ceta"]}}
        ]},
        {"label": "counters", "params": [
            {"label": "cem00258", "value": 55}, {"label": "cem00263", "value": 33}
        ]}
      ]
    }

**``cameras`` section** - lists which detector(s) each microscope has been
fitted with over time (a Krios can be swapped between K3/Falcon3/Ceta,
etc.). ``config:sessions.acquisition`` doesn't have a "camera model" field
today (only numeric voltage/magnification/pixel_size/dose/cs), so this
doesn't map 1:1. Suggested use: when filling in the real ``acquisition``
defaults per microscope, use the *current* camera from this list to pick
correct pixel_size/dose defaults, and optionally extend each microscope's
``entry_form:*_extra`` (e.g. ``entry_form:krios01_extra``, see
``emhub/data/imports/test_instance_data.json`` for the pattern) with a
``camera`` enum field using these choices, so operators can record which
detector was used per session rather than assuming a fixed one.

Update (2026-09-22, Gerrit)
----------------------------

Filled in real acquisition values (voltage, magnification, pixel
size, dose, cs) for each microscope in
``scripts/20260921_fix_sll_missing_configs.py`` (``CONFIG_SESSIONS``).
Got the values from Mathieu. 

Skipped the optional camera-selection field suggested above, not
needed anymore. This info should be extracted from the microscope-generated
metadata in the future.
One more thing found while checking if the old camera list was really
unused: The camera list itself and the
``get_session_cameras()`` function are genuinely dead, not used
anywhere in the code. But 109 real sessions do have a camera value
saved (K2, K3, Falcon3, Ceta, Ceta-D) - just under the wrong key,
the word "undefined" instead of "camera". Looks like an old
bug where a form field wasn't set up correctly. All 109 sessions are
from Feb-April 2022, so it was used for two months then never
again. But that does not seem important for now.

**``counters`` section** - keys look like ``cem#####`` (also ``dbb``,
``fac``, ``ext`` - see section 7), matching ``applications.code`` in the
live DB lowercased. **This is not historical/redundant data** - it's the
live running counter ``DataManager.get_new_session_info()`` reads and
increments every time a new Session is created without an explicit name,
to generate that session's unique code. As of 2026-09-22 it has 93
entries and is updated on essentially every new session. See section 7
for the full mechanism and why the earlier guidance here (cross-check
against bookings, then archive/delete) was wrong - deleting it would
reset every counter to 1 and break new-session creation for every
application that already has sessions.

Suggested migration steps
--------------------------

#. Decide real ``config:sessions.acquisition`` values per microscope
   (voltage, magnification, pixel_size, dose, cs), using the camera list
   above as a cross-reference.
#. Push them with ``dm.update_config('sessions', {...})`` (or extend
   ``scripts/20260921_fix_sll_missing_configs.py``'s ``CONFIG_SESSIONS``
   constant and re-run it - the script updates in place if the form
   already exists).
#. Do **not** delete ``sessions_config`` or its ``counters`` section -
   see section 7. It's actively read by session creation, not unread
   legacy data. The ``cameras`` section can be archived/removed
   independently once its values are folded into ``config:sessions``
   (or a per-microscope ``entry_form:*_extra``), since nothing reads
   ``cameras`` programmatically today.

3. ``config:permissions`` - rules for allowing booking on other instrument types
====================================================================================

How the check actually works
-----------------------------

``DataManager.check_resource_access(resource, permissionKey)``
(``emhub/data/data_manager.py``) grants access if **any** entry in
``config:permissions[permissionKey]`` (e.g. ``create_booking``) has its key
as a **substring of** ``resource.tags``, and its role list either contains
the literal string ``"user"`` (meaning: any authenticated user, regardless
of their actual role - see below) or the current user actually has one of
the listed roles:

.. code-block:: python

    def _user_allowed(roles):
        return 'user' in roles or self._user.has_any_role(roles)

    r = any(t in resource.tags and _user_allowed(u)
            for t, u in perms.get(permissionKey, {}).items())

Important nuance: ``"user"`` in a role list is a **sentinel meaning "open
to everyone signed in"**, not "only users with the ``user`` role". Managers
always bypass this check entirely (``is_manager`` short-circuits before
it).

Current tag coverage (after the 2026-09-21 fix)
--------------------------------------------------

``config:permissions.create_booking`` / ``.delete_booking`` cover the tags
``microscope``, ``instrument``, ``service``, each open to
``["admin", "manager", "user"]`` (i.e. open to everyone). Resources and
their live ``tags`` (``resources.tags`` in ``emhub.sqlite``):

.. list-table::
   :header-rows: 1

   * - Resource
     - tags
     - Covered?
   * - Solna Krios α / β
     - ``microscope krios solna``
     - yes (``microscope``)
   * - Talos
     - ``microscope talos solna``
     - yes (``microscope``)
   * - Umeå Krios
     - ``microscope krios umea``
     - yes (``microscope``)
   * - Umeå Glacios
     - ``microscope glacios umea``
     - yes (``microscope``)
   * - Vitrobot 1 / 2, Carbon Coater
     - ``instrument solna``
     - yes (``instrument``)
   * - Leica Cryo-CLEM
     - ``instrument, solna``
     - yes (``instrument``, substring match survives the comma)
   * - Users Drop-in
     - ``service solna``
     - yes (``service``)
   * - Chamaleon
     - ``Cham``
     - **no**
   * - Umeå Aquilos 2
     - ``Umeå cryo-FIB-SEM``
     - **no**
   * - Mass Photometry
     - ``Refeyn``
     - **no**
   * - Rapid Support Data Processing
     - *(empty)*
     - **no**
   * - Primo
     - *(empty)*
     - **no**

How to add a new instrument type
-----------------------------------

Two equivalent options - pick whichever fits how the resource is tagged
today:

**Option A - reuse a generic tag** (preferred if the resource is really
"just another instrument/service"): edit the resource's ``tags`` field
(Admin -> Resources) to include ``microscope``, ``instrument``, or
``service`` as appropriate. No ``config:permissions`` change needed - it's
already covered.

**Option B - add a specific permission entry** keyed on the resource's
actual tag, for cases where the access rule should differ from the generic
one (e.g. FIB-SEM needs manager-only booking even though other instruments
are open):

.. code-block:: json

    "create_booking": {
      "microscope": ["admin", "manager", "user"],
      "instrument": ["admin", "manager", "user"],
      "service": ["admin", "manager", "user"],
      "Umeå cryo-FIB-SEM": ["admin", "manager"]
    }

Add the same key under ``delete_booking`` if deletion should follow the
same rule (it doesn't have to - they're independent dicts).

Rule of thumb: **any substring match wins** (``any()`` over all entries),
so you can layer a broad rule (``"instrument"``) with a narrower exception
(``"talos"``, ``"Refeyn"``) on a more specific tag substring, and the more
permissive of the two that matches will apply. If you want an instrument to
be *more* restricted than the generic tag would allow, it must NOT carry
that generic tag at all (tagging something ``instrument`` will always make
it bookable per the ``instrument`` rule, regardless of other entries).

Open item
-----------

Chamaleon, Umeå Aquilos 2, Mass Photometry, Rapid Support Data Processing
and Primo are currently manager-only to book (no matching tag/permission
entry). Confirm with Jose whether that's intentional per-instrument, or
whether they should get a generic tag (Option A) or their own entry
(Option B).

Update (2026-09-23, Gerrit)
----------------------------

Updated the tags in SLL Live instance (emhub.cryoem.se) via GUI.

.. list-table::
   :header-rows: 1

   * - Resource
     - Old tags
     - New tags
     - Covered by
   * - Chamaleon
     - ``Cham``
     - ``instrument solna``
     - ``instrument``
   * - Umeå Aquilos 2
     - ``Umeå cryo-FIB-SEM``
     - *pending* - waiting for Umeå decision
     - *pending*
   * - Mass Photometry
     - ``Refeyn``
     - ``instrument solna``
     - ``instrument``
   * - Rapid Support Data Processing
     - *(empty)*
     - ``service solna``
     - ``service``
   * - Primo
     - *(empty)*
     - ``instrument solna``
     - ``instrument``

4. Invoice Periods page crash: PortalManager unreachable locally (found 2026-09-22)
========================================================================================

.. note::

   ``PortalManager`` (and the file paths below referring to
   ``emhub/data/imports/scilifelab.py``) moved out of core into this repo
   later the same day - see section 5. The bug and fix described here are
   unaffected by the move, just the file's location.

Problem
-------

Clicking into an Invoice Period's "invoices" tab (``/get_content`` ->
``invoice_period`` -> ``reports_invoices()`` in
``emhub/data/content/dc_reports.py``) broke the page on the local instance,
which has no network access to the real Portal
(``https://cryoem.scilifelab.se/api/v1/``, from ``SLL_PORTAL_API`` in
``config.py``).

What's actually pulled from the Portal here: just one call,
``dc.app.sll_pm.fetchAccountsJson()``, filtered down to PI accounts, to get
each PI's ``invoice_ref`` and ``invoice_address`` (address/zip/city/country)
for the "Invoice Reference" / "Invoice Address" columns. Everything else on
the page (bookings, costs, days, applications) comes from the local DB.

``reports_invoices()`` already had a ``hasattr(dc.app, 'sll_pm')`` guard,
but that didn't help: ``app.sll_pm`` is constructed unconditionally in core
(``emhub/__init__.py``) whenever ``SLL_PORTAL_API`` is present in
``config.py`` - which it is, even on a local checkout, since ``config.py``
was copied from production. The object exists; it just can't reach the
network. The underlying ``PortalManager._fetchJsonFromUrl()``
(``emhub/data/imports/scilifelab.py``) had no ``timeout`` and no
try/except around ``requests.get()``, so an unreachable Portal raised an
uncaught ``requests.exceptions.ConnectionError`` (or could hang
indefinitely with no timeout at all) straight through to the page. A
second, independent bug: ``emhub/templates/invoices_list.html`` had one of
its two rendering paths (the ungrouped/"Show Application Groups" view) doing
bare ``portal_users[pi_info['pi_email']]`` with no fallback, unlike the
grouped view a few lines above it which already used
``portal_users.get(pi_info['pi_email'], default_pu)``.

Fix (in core, ``emhub`` repo - this is shared code, not SLL-specific)
------------------------------------------------------------------------

- ``emhub/data/imports/scilifelab.py``: ``PortalManager._fetchJsonFromUrl``
  now sets ``timeout=10`` and catches ``requests.exceptions.RequestException``,
  returning ``None`` instead of raising. ``fetchOrdersJson()`` and
  ``fetchAccountsJson()`` (which used to do a bare ``['items']`` on the
  result) now return ``[]`` when the fetch failed instead of raising
  ``TypeError: 'NoneType' object is not subscriptable``. This also fixes
  the same crash on the "Import from Portal" admin pages (Import Users /
  Import Applications), which hit the same ``sll_pm`` object.
- ``emhub/templates/invoices_list.html``: the ungrouped view's
  ``portal_users[...]`` lookup now uses the same ``.get(..., default_pu)``
  fallback as the grouped view, so a PI missing from ``portal_users``
  (empty dict, or genuinely not in the Portal) renders blank invoice
  ref/address cells instead of crashing.

Together these mean: with no Portal access, Invoice Periods (and the
Import from Portal pages) now render normally with blank invoice
reference/address fields, instead of a broken page - and if the Portal
*is* reachable, behavior is unchanged.

5. Moving ``PortalManager`` into this repo (2026-09-22)
=========================================================

Problem
-------

``PortalManager`` (and the one-time DB-seeding tool ``PortalData`` that
lived alongside it) were part of core, at
``emhub/data/imports/scilifelab.py``, even though both classes are
entirely SLL-specific: they talk to the SciLifeLab Order Portal REST API
and import Portal JSON exports. Core's ``create_app()`` also
unconditionally constructed ``app.sll_pm`` inline whenever
``SLL_PORTAL_API`` was present in ``config.py``, which meant core carried
SLL-only code and every other EMhub instance's ``create_app()`` ran a
dead ``if`` check for a config key that only ever applies to SLL. A grep
confirmed nothing else in core, or in any other instance customization
(e.g. ``emhub-stjude-cryoem``), imported anything from
``scilifelab.py`` - it was safe to move the whole file, not just extract
one class.

Fix
---

- Moved ``emhub/data/imports/scilifelab.py`` (core) to
  ``portal.py`` in this repo, unchanged apart from the module docstring
  and the ``__main__`` usage message (it can no longer be run as
  ``python -m emhub.data.imports.scilifelab ...`` since it's outside the
  ``emhub`` package now - run it directly as ``python portal.py ...``
  instead, from an environment where ``emhub`` is importable).
- Added ``app_setup.py`` to this repo (this instance had none before).
  Its ``setup_app(app)`` reads ``app.config.get('SLL_PORTAL_API', None)``
  and, if set, builds a ``PortalManager`` and attaches it as
  ``app.sll_pm`` - the exact same behavior core used to have inline,
  just relocated. It loads ``portal.py`` with an explicit
  ``importlib.util.spec_from_file_location`` (the same technique core's
  own ``load_module()`` uses for extension files), rather than adding
  this directory to ``sys.path``, since ``load_module()`` doesn't put
  loaded extension modules' own directory on the path.
- Removed the inline ``portalAPI``/``PortalManager`` block from core's
  ``emhub/__init__.py``. Core's existing ``app_setup`` extension hook
  (``load_module('app_setup')``, called after ``app.dm`` is built) now
  does this instead, so it only runs for instances that actually opt in
  by shipping an ``app_setup.py`` with a ``setup_app()`` function.

Not changed / out of scope
---------------------------

Two call sites still access ``app.sll_pm`` without a ``hasattr`` guard
(``emhub/blueprints/api.py`` and ``dc_base.py``'s
``account_form()``) - same as before the move, not a regression, but
worth knowing: on an instance with no ``SLL_PORTAL_API`` configured at
all (unlike the local SLL checkout, which has it but can't reach the
network), hitting those specific pages/endpoints would raise
``AttributeError: 'Flask' object has no attribute 'sll_pm'``. Only
``dc_reports.py`` guards with ``hasattr(dc.app, 'sll_pm')``. Left alone
since it predates this change and wasn't part of what was asked.

6. Moving the remaining ``app.sll_pm`` call sites into this repo (2026-09-22)
=================================================================================

Problem
-------

After moving ``PortalManager`` itself (section 5), a grep for every
remaining ``sll_pm`` reference in core turned up three call sites:

.. list-table::
   :header-rows: 1

   * - Location
     - What it did
     - Guarded?
   * - ``emhub/blueprints/api.py``, ``/import_application`` route
     - Import an Application from a Portal order code
     - No - unconditional ``app.sll_pm.fetchOrderDetailsJson(...)``
   * - ``emhub/data/content/dc_base.py``, ``_get_users_from_portal()``
     - Helper to list/import Portal accounts as EMhub users
     - No, but its only caller was already broken (see below)
   * - ``emhub/data/content/dc_reports.py``, ``reports_invoices()``
     - Enrich the Invoice Periods report with PI invoice ref/address
     - Yes - ``hasattr(dc.app, 'sll_pm')`` (see section 4)

The first two are 100% SLL-Portal-specific (nothing generic about them)
and had no business living in core, unguarded, where every other instance
pays for a dead ``if`` check and risks an ``AttributeError`` if it ever
hits that code path. The third (``reports_invoices()``) is different: it's
embedded in the otherwise-generic Invoice Periods report, already
degrades gracefully via its ``hasattr`` guard, and extracting just that
snippet would need a new plugin hook that doesn't exist yet - left alone,
lower priority, not a correctness problem today.

While moving the first two, a bigger problem turned up: the SLL repo's
own ``data_content.py`` already had matching content functions
(``get_portal_users_list``, ``get_portal_import_application``,
``get_applications_check``) meant to back the "Import Users" / "Import
Applications" admin pages (linked from ``main_left_sidebar.html``) - but
**none of them were reachable**. ``register_content(dc)`` defined them as
nested closures and returned without ever calling ``dc.content(...)`` on
them (which is how a function gets added to ``dc._contentDict``), and two
of the three function names didn't even match the ``content_id`` values
the templates request (``portal_users_list`` vs. the defined
``get_portal_users_list``, etc.). On top of that, all three referenced an
undefined ``self`` (they're plain functions inside ``register_content()``,
not methods), and the file never imported ``flask``, ``datetime`` or
``datetime_from_isoformat``, all of which the function bodies use. Calling
any of these content_ids would have failed with ``Missing content
function for '...'`` (unregistered) or, had they been registered as
written, ``NameError: name 'self' is not defined``. This looks like it
was broken from the start, not a regression - the feature was never
working on this instance.

Fix
---

- Core: removed ``/import_application`` from ``emhub/blueprints/api.py``
  and ``_get_users_from_portal()`` from ``emhub/data/content/dc_base.py``,
  each replaced with a short comment pointing here.
- This repo: added ``api.py`` (new - this instance had none before),
  whose ``extend_api(api_bp)`` registers ``/import_application`` exactly
  as it worked in core, now scoped to instances that ship this file.
- This repo: rewrote ``data_content.py`` - moved
  ``_get_users_from_portal()`` in as a local helper (using ``dc.app``
  instead of the undefined ``self.app``), renamed the three functions to
  match the ``content_id`` values the templates already use
  (``portal_users_list``, ``portal_import_application``,
  ``applications_check``), registered each with ``@dc.content``, and
  added the missing ``flask``/``datetime``/``datetime_from_isoformat``
  imports. The "Import Users from Portal" and "Import Applications from
  Portal" admin pages (sidebar links already existed) should now actually
  work, network access to the Portal permitting.
- Moved the two templates these content functions render,
  ``portal_users_list.html`` and ``portal_import_application.html``, from
  core's ``emhub/templates/`` into this repo's ``templates/`` - they were
  100% Portal-specific and only ever linked from this repo's own sidebar.
  Safe to relocate: the instance's ``extra/templates`` folder is searched
  *before* core's (see ``template_folders`` in ``emhub/__init__.py``), so
  Jinja still resolves them the same way, and neither template is
  referenced anywhere else by filename.
- Verified: ``py_compile`` clean on every changed/new ``.py`` file in both
  repos, a plain ``jinja2.Environment().parse()`` on both moved templates,
  and a repo-wide grep confirming ``sll_pm`` only remains in the one
  already-guarded core call site (``dc_reports.py``).

Not changed / still worth a look
-----------------------------------

- ``reports_invoices()`` in core (section above) - left in core since it's
  already optional and embedded in generic report code.
- ``applications_check`` has no sidebar link yet (unlike the other two) -
  it's now reachable at ``content_id=applications_check`` if you want to
  wire up a page for it, but nothing does today.
- This move only fixed the *reachability* bugs (registration, ``self``,
  imports). It did not test the features end-to-end against a live Portal
  connection - worth a manual smoke test once there's network access to
  ``https://cryoem.scilifelab.se``.

7. How session unique codes (``cem00734_00044``, ``dbb01967``, ...) are assigned (found 2026-09-22)
========================================================================================================

Summary
-------

Live SLL data (2,822 sessions, checked 2026-09-22): every session name
falls into one of four prefixes, generated from the session's booking's
linked ``Application.code``, with **zero exceptions** (no duplicates, no
other prefixes, no ``int`` prefix):

.. list-table::
   :header-rows: 1

   * - Prefix
     - Count
     - Source
   * - ``dbb``
     - 1,466
     - the internal ``DBB`` application (``code='DBB'``)
   * - ``cem``
     - 1,029
     - a ``CEM#####`` application code, lowercased
   * - ``fac``
     - 177
     - booking has **no** linked application (facility-internal)
   * - ``ext``
     - 150
     - an ``EXT#####`` application code, lowercased

(No ``int`` prefix exists in this instance's data today - if you had that
in mind from another facility/example, it isn't one of the patterns SLL
currently uses; nothing hardcodes ``int`` anywhere in core either. It
would appear automatically the same way ``ext``/``cem`` do, the day an
application with a code starting ``INT`` is created.)

Core logic (``emhub/data/data_manager.py``)
-----------------------------------------------

``DataManager.get_new_session_info(booking_id)`` (has its own
``# FIXME: This is specific to SLL and needs cleanup/refactoring``
comment already in core) generates the code:

.. code-block:: python

    def get_new_session_info(self, booking_id):
        b = self.get_bookings(condition="id=%s" % booking_id)[0]
        a = b.application
        code = 'fac' if a is None else a.code.lower()
        sep = '' if len(code) == 3 else '_'
        c = self.get_session_counter(code)
        return {'code': code, 'counter': c,
                'name': '%s%s%05d' % (code, sep, c)}

- ``code`` = the booking's application code lowercased (``CEM00734`` ->
  ``cem00734``, ``DBB`` -> ``dbb``, ``EXT00001`` -> ``ext00001``), or the
  literal string ``'fac'`` if the booking has no linked application at
  all (not derived from any application - just a hardcoded fallback).
- ``sep`` is empty only when ``code`` is exactly 3 characters - which in
  practice only happens for ``fac`` and ``dbb`` (``DBB`` is a 3-letter
  application code). Every ``CEM``/``EXT`` code is longer than 3 chars,
  so those always get an underscore before the counter.
- ``c`` / the counter comes from ``get_session_counter(code)``, which
  reads it from ``sessions_config``'s ``counters`` section (see section
  2, now corrected) - ``self.get_form_by(name='sessions_config')``,
  section ``label == 'counters'``, ``{'label': code, 'value': N}``. If
  the form or that code's entry is missing, it defaults to ``1``.
- The name is formatted ``'%s%s%05d'`` - code, separator, 5-digit
  zero-padded counter. This exactly matches ``cem00734_00044``,
  ``dbb01967``, ``fac00458``, ``ext00001_00007``.

This only runs when ``create_session()`` is called **without** an
explicit ``name`` in ``attrs``:

.. code-block:: python

    # DataManager.create_session()
    if 'name' not in attrs:
        session_info = self.get_new_session_info(b.id)
        attrs['name'] = session_info['name']
    else:
        session_info = None
    s = self.get_session_by(name=attrs['name'])
    if s is not None:
        raise Exception("Session name already exist, choose a different one.")
    ...
    session = self.__create_item(self.Session, **attrs)
    if session_info:
        self.update_session_counter(session_info['code'], session_info['counter'] + 1)

Uniqueness is enforced at the application level (a lookup + raise), not
by a DB constraint - ``Session.name`` is ``String(256), nullable=False``
with no ``unique=True``. It happens to hold in practice (0 duplicates in
2,822 rows) only because the counter is always incremented right after a
successful create.

There's a second piece: ``DataManager.update_session()`` re-syncs the
counter forward if a session's name is edited (or created with an
explicit name) to something matching the auto-generated pattern -
``Session.is_code_counted`` (``emhub/data/data_models.py``) checks
``re.match("[a-z]{3}[0-9]{5}", name)``. If the edited name's counter is
higher than what's stored, the stored counter is bumped to match + 1 -
but only ever forward, never back. This is what would keep things
consistent if someone manually created/renamed a session with a
higher-numbered code than the auto-generator would have picked.

Fixed (2026-09-22): the "New Session" dialog now uses this path on SLL
---------------------------------------------------------------------------

``emhub/templates/create_session_form.html`` (core) is the browser
dialog behind the "New Session" button (the
one whose ``content_id`` routing we fixed in section 1/the ``KeyError:
content_id`` bug). Its JS:

.. code-block:: javascript

    let sessionName = formValues.session_name;
    if (nonEmpty(sessionName)) {
        attrs.name = sessionName;
        ...
    }
    var valid_name = nonEmpty(attrs.name) && regex.test(attrs.name);
    if (!valid_name) {
        showError("Provide a valid <strong>Session Name</strong>...");
        return;
    }
    // Add unique prefix to avoid session name clashes
    attrs.name = "{{ session_name_prefix }}" + attrs.name;

As written, this **always** requires the operator to type a name (the
``showError``/``return`` fires whenever it's empty - there's no path
that submits without one), and always prepends
``session_name_prefix`` (``f'{dateStr}{resource.name}:'``, e.g.
``"20260922Solna Krios α:"``) client-side before calling
``/api/create_session``. That means ``attrs.name`` is **always** present
in the request, so server-side ``get_new_session_info()`` auto-naming
(above) never triggers through this dialog - and the result would
contain a colon, in a completely different format from every one of the
2,822 existing SLL session names (confirmed: 0 of them contain a colon).

This dialog's ``content_id`` (``create_session_form``, wired via
``config:sessions.create_session``) was **missing/broken on this
instance until this repo's 2026-09-21 fix** (section 1) - so none of the
existing session data could have come from this exact current code path
on SLL. It most likely came from an older version of this template (git
history shows the ``session_name_prefix`` prepend and the mandatory-name
JS gate are relatively recent core commits, Jul/Oct 2025) and/or from
direct API/script usage that omits ``name`` on purpose. Either way: now
that the dialog is reachable again, using it as-is on SLL will produce
names that break the ``cem``/``dbb``/``fac``/``ext`` convention this
facility's reporting and invoicing (section on ``config:permissions``
tag coverage, invoice periods) implicitly relies on.

Fix
---

Went with the first option (leave manual-name as an opt-in override
rather than changing what ``session_name_prefix`` means), via the same
override pattern already used for ``dashboard_right.html``: core's
``create_session_form.html`` and core's ``create_session_form`` content
function (``emhub/data/content/dc_sessions.py``) are both left untouched
- this repo now ships its own versions of both, which win via the
existing override mechanisms (``extra/templates`` searched before core's
templates; ``register_content(dc)`` here runs after core's, so
re-registering ``create_session_form`` with ``@dc.content`` replaces
core's entry in ``dc._contentDict``).

- ``data_content.py``: added a ``create_session_form`` override,
  identical to core's version, plus one addition -
  ``session_info = dm.get_new_session_info(booking_id)``, exposed to the
  template as ``suggested_session_name``. This is a pure read (the
  counter is only consumed/incremented inside an actual
  ``create_session()`` call), so it's safe to compute on every render,
  even if the operator opens the dialog without submitting.
- ``templates/create_session_form.html`` (new, copied from core):
  identical to core except the Session Name field -

  - Now shows a hint below it: "Next auto-assigned code:
    **<suggested_session_name>**. Only type a name above to override it
    (e.g. a special/debugging session)." (2026-09-22 follow-ups: the
    first version of this hint used a negative ``margin-top`` to tuck it
    under the input, which instead overlapped it and was hard to read -
    replaced with a normal, non-negative ``form-group row`` (empty
    ``col-3`` spacer + ``col-8``) so it sits cleanly below the input,
    aligned with it, same as every other field in this form. Also
    dropped the ``<small>`` tag, which forced an 80%-scaled font on top
    of the already-small hint text - it's a plain ``text-muted`` div at
    normal (``1rem``) size now, still visually secondary via color
    alone rather than size.)
  - The JS no longer requires a name. Left blank, ``attrs.name`` is
    never set in the request, so ``DataManager.create_session()``'s
    existing ``if 'name' not in attrs:`` branch auto-generates it via
    ``get_new_session_info()`` - no core change needed, this path
    already existed and worked, it just had no way to be reached from
    SLL's UI.
  - Typing a name still validates it with the same regex as before, but
    no longer gets any prefix prepended - it's sent to the server
    exactly as typed. This preserves the existing "special/debugging
    session" behavior (RAW/OTF path overrides, ``tasks: []`` to skip
    scheduling a transfer task) unchanged, tied to the same "did the
    operator type a name" condition as core's original template - only
    the requirement and the prefix were removed.

Verified: ``py_compile`` on ``data_content.py``, a ``jinja2.Environment().parse()``
on the new template, and confirmed ``config:sessions.create_session``
already maps all 5 microscopes to ``content_id: create_session_form``
(set by the 2026-09-21 fix script), so no config change was needed for
the override to take effect.

Not verified: an actual end-to-end session creation against the live
server (this is an offline dev checkout - see the Checklist). In
particular, whether ``project_id``/extra-form data should still be
saved when the name is left blank (today, exactly like core's original
code, that ``attrs.extra`` block is only sent when a name is typed) is
worth confirming with a real "leave it blank" submission before relying
on this for production sessions - flagged in the Checklist rather than
guessed at here.

Checklist
=========

- [x] Create missing ``config:*`` forms (script written and ready to run)
- [ ] Run ``scripts/20260921_fix_sll_missing_configs.py`` against the live
      SLL server
- [x] Fill in real ``config:sessions.acquisition`` values per microscope
- [ ] Decide fate of ``sessions_config`` (archive vs delete) after
      verifying the ``counters`` section against real booking/session
      history
- [ ] Decide booking permissions for Chamaleon / Aquilos 2 / Mass
      Photometry / Rapid Support Data Processing / Primo
- [x] Make PortalManager degrade gracefully when the Portal is unreachable
      (core fix, needs the ``emhub`` core repo's changes pulled/deployed
      to take effect - not something this repo can fix on its own)
- [x] Move PortalManager/PortalData out of core into this repo, wired up
      via a new ``app_setup.py`` (needs the ``emhub`` core repo's
      ``emhub/__init__.py`` change pulled/deployed too)
- [x] Move the remaining ``app.sll_pm`` call sites (``/import_application``
      API route, ``_get_users_from_portal()``) out of core into this
      repo's ``api.py``/``data_content.py``, and fix the pre-existing bugs
      that left "Import Users/Applications from Portal" unreachable
- [ ] Smoke-test "Import Users from Portal" and "Import Applications from
      Portal" against a live Portal connection (not possible from this
      offline dev checkout)
- [x] Fix the "New Session" dialog to use SLL's auto-numbering
      (cem/dbb/fac/ext + counter) instead of requiring a typed name with
      a date/resource prefix that matched no existing SLL session name
      (see section 7)
- [ ] Smoke-test the "New Session" dialog end-to-end against a live
      server: confirm a blank-name submission gets the suggested
      auto-assigned code, and decide whether project_id/extra-form data
      should be saved even when the name is left blank (today it isn't,
      matching core's original - never-reachable - behavior)
- [x] Correct section 2's guidance on ``sessions_config``'s ``counters``
      section - it is live, load-bearing state (session code
      auto-numbering), not safe to archive/delete as originally written
