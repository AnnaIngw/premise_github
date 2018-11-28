"""Construct LCAs for REMIND technologies and regions."""

import brightway2 as bw
from helpers.eimod import geomatcher

def remove_double_counting(lca, activities_of_interest, all_activities):
    """Modify the LCA inventory by excluding ``all_activities`` that are not
    ``activities_of_interest``.

    * ``lca`` is an ``LCA`` object for which LCI and LCIA have already been calculated
    * ``activities_of_interest`` is an iterable of activity objects
    * ``all_activities`` is an iterable of *all* activity objects

    Returns the LCA object.
    """

    to_key = lambda x: x if isinstance(x, tuple) else x.key

    exclude = set([to_key(o) for o in all_activities]).difference(
              set([to_key(o) for o in activities_of_interest]))

    for activity in exclude:
        row = lca.product_dict[activity]
        col = lca.activity_dict[activity]
        production_amount = lca.technosphere_matrix[row, col]
        lca.technosphere_matrix[row, :] *= 0
        lca.technosphere_matrix[row, col] = production_amount

    lca.lci_calculation()
    return lca


def multi_lca_average(actvts, demand=1.):
    """ Perform LCA calculations for multiple technologies (activities).
        The demand is distributed evenly over all found activities (average).
    """

    share = 1./len(actvts)

    lca = bw.LCA({act: demand*share for act in actvts})
    lca.lci()

    return lca


def find_activities_by_name(techname, db):
    return [act for act in db if act["name"] == techname]


def find_activities_in_regions(techname, regions, db):
    actvts = find_activities_by_name(techname, db)
    if len(actvts) == 0:
        actvts = [act for act in db if act["name"] == techname and
                  act["location"] == "RoW"]
        if len(actvts) == 0:
            actvts = [act for act in db if act["name"] == techname and
                      act["location"] == "GLO"]
            if len(actvts) == 0:
                print("Could not find any activities matching {}".format(techname))
    return actvts



def multiregion_lca_without_double_counting(activity_name, all_activities, regions, db, demand=1.):
    """Calculate inventory for ``activity_of_interest`` but excluding
    contributions from ``activities_to_exclude``.

    * ``activity_name`` is a string identifiying an ecoinvent activity without specifying the location.
    * ``all_activities`` is a full list of ``activities``.
        Those that are not found using ``activity_name`` are excluded.
    * ``demand`` is the demand for the activity.
    * ``regions`` is a list of region codes.

    Returns the LCA object.
    """

    to_key = lambda x: x if isinstance(x, tuple) else x.key

    # find all relevant activities
    activities_of_interest = find_activities_in_regions(activity_name, regions, db)

    # activities that are not of interest are excluded
    exclude = set([to_key(o) for o in all_activities]).difference(
                  set([to_key(o) for o in activities_of_interest]))

    # perform LCA to obtain technosphere matrix
    lca = multi_lca_average(activities_of_interest, demand)
    lca.lci()

    # adjust technosphere matrix
    for activity in exclude:
        row = lca.product_dict[activity]
        col = lca.activity_dict[activity]
        production_amount = lca.technosphere_matrix[row, col]
        lca.technosphere_matrix[row, :] *= 0
        lca.technosphere_matrix[row, col] = production_amount

    lca.lci_calculation()
    return lca


def lca_for_multiple_techs_and_regions(techs, regions, db, units_and_conversions={}):
    """ Perform LCA calculations for multiple technologies (activities) and regions.
        The demand is distributed evenly over all found activities (average).
    """
    if len(techs) == 0:
        return None
    # print("LCA for activities (from {}): {}".format(db.name, techs))
    actvts = [act for act in db if act["name"] in techs and
              act["location"] in regions]
    if len(actvts) == 0:
        actvts = [act for act in db if act["name"] in techs and
                  act["location"] == "RoW"]
        if len(actvts) == 0:
            actvts = [act for act in db if act["name"] in techs and
                      act["location"] == "GLO"]
            if len(actvts) == 0:
                print("Could not find any activities matching {}".format(techs))
                return None

    # set demand to portion
    # TODO: Somehow seperate heat and power generation for CHP
    if hasattr(actvts[0], "demand"):
        raise Exception("Activity object changed: demand attribute found.")

    share = 1./len(actvts)
    for act in actvts:
        if act["unit"] in units_and_conversions.keys():
            act.demand = share * units_and_conversions[act["unit"]]
        else:
            print("WARNING: Irregular units found for {}: {}.".format(act, act["unit"]))

    lca = bw.LCA({act: act.demand for act in actvts})
    lca.lci()

    return lca


def ei_locations_in_remind_region(region):
    regions = [
        el[1] if type(el) == tuple else el for el in geomatcher.contained(("REMIND", region))]
    if region == "EUR":
        regions.append("RER")
    return regions


def get_REMIND_database_name(scenario, year):
    return "_".join(["ecoinvent", "Remind", scenario, str(year)])


def act_fltr(db, fltr={}, mask={}, filter_exact=False, mask_exact=False):
    """Filter `db` for activities matching field contents given by `fltr` excluding strings in `mask`.

    Args:
      `db`: brightway database object.
      `fltr`: string, list of strings or dictionary.
        If a string is provided, it is used to match the name field from the start (*startswith*).
        If a list is provided, all strings in the lists are used and results are joined (*or*).
        A dict can be given in the form <fieldname>: <str> to filter for <str> in <fieldname>.
      `mask`: used in the same way as `fltr`, but filters add up with each other (*and*).
      `filter_exact` and `mask_exact`: boolean, set `True` to only allow for exact matches.

    Returns:
      list of brightway activities
    """
    result = []

    # default field is name
    if type(fltr) == list or type(fltr) == str:
        fltr = {
            "name": fltr
        }
    if type(mask) == list or type(mask) == str:
        mask = {
            "name": mask
        }

    def like(a, b):
        if filter_exact:
            return a == b
        else:
            return a.startswith(b)

    def notlike(a, b):
        if mask_exact:
            return a != b
        else:
            return b not in a

    assert len(fltr) > 0, "Filter dict must not be empty."
    for field in fltr:
        condition = fltr[field]
        if type(condition) == list:
            for el in condition:
                # this is effectively connecting the statements by *or*
                result.extend([act for act in db if like(act[field], el)])
        else:
            result.extend([act for act in db if like(act[field], condition)])

    for field in mask:
        condition = mask[field]
        if type(condition) == list:
            for el in condition:
                # this is effectively connecting the statements by *and*
                result = [act for act in result if notlike(act[field], el)]
        else:
            result = [act for act in result if notlike(act[field], condition)]
    return result


techno_filters = {
    "steel": {
        "fltr": "market for steel,",
        "mask": "hot rolled"},
    "concrete": {"fltr": "market for concrete,"},
    "copper": {
        "fltr": "market for copper",
        "filter_exact": True},
    "aluminium": {
        "fltr": ["market for aluminium, primary",
                 "market for aluminium alloy,"]},
    "electricity": {"fltr": "market for electricity"},
    "gas": {
        "fltr": "market for natural gas,",
        "mask": ["network", "burned"]},
    "diesel": {
        "fltr": "market for diesel",
        "mask": ["burned", "electric"]},
    "petrol": {
        "fltr": "market for petrol,",
        "mask": "burned"},
    "freight": {"fltr": "market for transport, freight"},
    "cement": {"fltr": "market for cement,"},
    "heat": {"fltr": "market for heat,"}
}


def add_REMIND_technosphere_flows(reset_flows=False):
    """Add material flows within ecoinvent as biosphere endpoints to account
    for these flows in REMIND scenarios.

    Args:
      `reset_flows`: if `True` remove existing flows from activities.
    """

    available_tech_markets = []
    for db in bw.databases:
        if db.startswith("ecoinvent_Remind_"):
            print("Search tech markets for {}.".format(db))
            eidb = bw.Database(db)

            techno_markets = {
                tech: act_fltr(eidb, **conditions) for tech, conditions in techno_filters.items()}

            print("Check for consistent units across technologies.")
            for kind, actlst in techno_markets.items():
                for act in actlst:
                    if act["unit"] != actlst[0]["unit"]:
                        print("Activity `{}` of kind {} has unit {}.".format(act, kind, act["unit"]))
                        raise("Units are not aligned!")

            print("Add inventory flows to database.")
            inventory = bw.Database("Inventory flows")
            for kind in techno_markets:
                if not [act for act in inventory if act["name"] == kind]:
                    inventory.new_activity(kind, **{
                        "name": kind,
                        "unit": techno_markets[kind][0]["unit"],
                        "type": "inventory flow",
                        "categories": ("inventory",),
                    })
                else:
                    print("Inventory flows already present.")
                    # let's assume they are all there
                    break

            print("Add flows to activities.")
            for kind, actlst in techno_markets.items():
                for act in actlst:
                    # clear exsiting exchanges
                    if reset_flows:
                        [ex.delete() for ex in act.exchanges() if ex["input"] == ("Inventory flows", kind)]
                    if not [ex for ex in act.exchanges() if ex["input"] == ("Inventory flows", kind)]:
                        act.new_exchange(**{
                            'input': ('Inventory flows', kind),
                            'type': 'biosphere',
                            'amount': 1
                        }).save()
                    else:
                        print("Modified activities found. Skipping.")