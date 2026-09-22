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

``sessions_config`` is a pre-rename form (no ``config:`` prefix) that
current core no longer reads - ``DataManager.get_config('sessions')`` only
ever looks up a form literally named ``config:sessions``. It's dead data
today, but it has two sections worth mining before it's archived, since
nothing else in the instance currently holds this information:

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

**``counters`` section** - keys look like ``cem#####``, which match
``applications.code`` in the live DB (confirmed: ``CEM00258``, ``CEM00263``,
etc. are real application codes, 147 total). These are very likely a manual
pre-``resource_allocation`` tally (days/sessions used per application) from
before the DB tracked this natively. They do **not** line up with the
current ``applications.resource_allocation`` JSON (``{"quota": {"krios": 0,
"talos": 0}, "noslot": []}`` for every application checked) - so this isn't
a 1:1 replacement, and the counters likely predate ``resource_allocation``
entirely. Before archiving:

- Cross-check a few counter values against actual ``bookings``/``sessions``
  rows for the same application/PI to see if they roughly match a
  historical session or booking count.
- If they do, they're safely redundant now (the DB can compute the same
  number live) and ``sessions_config`` can be deleted.
- If they don't match anything, export the raw JSON to a file before
  deleting the form, in case it records something not tracked elsewhere
  (e.g. an old invoicing tally).

Suggested migration steps
--------------------------

#. Decide real ``config:sessions.acquisition`` values per microscope
   (voltage, magnification, pixel_size, dose, cs), using the camera list
   above as a cross-reference.
#. Push them with ``dm.update_config('sessions', {...})`` (or extend
   ``scripts/20260921_fix_sll_missing_configs.py``'s ``CONFIG_SESSIONS``
   constant and re-run it - the script updates in place if the form
   already exists).
#. Verify the ``counters`` data isn't load-bearing (see above), then it's
   safe to leave ``sessions_config`` alone (harmless, unread) or delete it
   via the admin Raw Forms page.

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

Checklist
=========

- [x] Create missing ``config:*`` forms (script written and ready to run)
- [ ] Run ``scripts/20260921_fix_sll_missing_configs.py`` against the live
      SLL server
- [ ] Fill in real ``config:sessions.acquisition`` values per microscope
- [ ] Decide fate of ``sessions_config`` (archive vs delete) after
      verifying the ``counters`` section against real booking/session
      history
- [ ] Decide booking permissions for Chamaleon / Aquilos 2 / Mass
      Photometry / Rapid Support Data Processing / Primo
