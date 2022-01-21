"""
geomap.py contains the Geomap class that allows to find equivalents between
the IAM locations and ecoinvent locations.
"""

from typing import Dict, List, Union

import yaml
from wurst import geomatcher

from premise import DATA_DIR

ECO_IAM_MAPPING = DATA_DIR / "geomap" / "missing_definitions.yml"
IAM_TO_IAM_MAPPING = DATA_DIR / "geomap" / "mapping_regions_iam.yml"


def get_additional_mapping() -> Dict[str, str]:
    """
    Return a dictionary with additional ecoinvent to IAM mappings
    """
    with open(ECO_IAM_MAPPING, "r") as stream:
        out = yaml.safe_load(stream)

    return out


def get_iam_to_iam_mapping() -> Dict[str, str]:
    """
    Return a dictionary with IAM to IAM mappings
    :return: dictionary with IAM to IAM location mapping

    """
    with open(IAM_TO_IAM_MAPPING, "r") as stream:
        out = yaml.safe_load(stream)

    return out


class Geomap:
    """
    Map ecoinvent locations to IAM regions and vice-versa.

    :ivar model: IAM model (e.g., "remind", "image")

    """

    def __init__(self, model: str) -> None:

        self.model = model
        self.geo = geomatcher
        self.additional_mappings = get_additional_mapping()
        self.iam_to_iam_mappings = get_iam_to_iam_mapping()

        self.iam_regions = [
            x[1]
            for x in list(self.geo.keys())
            if isinstance(x, tuple) and x[0] == self.model.upper()
        ]

    def iam_to_ecoinvent_location(
        self, location: str, contained: bool = True
    ) -> Union[List[str], str]:
        """
        Find the corresponding ecoinvent region given an IAM region.
        :param location: name of a IAM region
        :param contained: whether only geographies that are contained within
        the IAM region should be returned. By default, `contained` is False,
        meaning the function also returns geographies that intersects with IAM region.
        :return: name(s) of an ecoinvent region
        """

        location = (self.model.upper(), location)

        ecoinvent_locations = []
        try:
            searchfunc = self.geo.contained if contained else self.geo.intersects
            for r in searchfunc(location):
                if not isinstance(r, tuple):
                    ecoinvent_locations.append(r)
                else:
                    if r[0] not in ("REMIND", "IMAGE"):
                        ecoinvent_locations.append(r[1])

            # Current behaviour of `intersects` is to include "GLO" in all REMIND regions.
            if location != (self.model.upper(), "World"):
                ecoinvent_locations = [e for e in ecoinvent_locations if e != "GLO"]
            return ecoinvent_locations

        except KeyError:
            print("Can't find location {} using the geomatcher.".format(location))
            return ["RoW"]

    def ecoinvent_to_iam_location(self, location: str) -> str:
        """
        Return an IAM region name for an ecoinvent location given.
        Set rules in case two IAM regions are within the ecoinvent region.
        :param location: ecoinvent location
        :return: IAM region name
        """

        # First, it can be that the location is already
        # an IAM location

        list_IAM_regions = [
            k[1]
            for k in list(self.geo.keys())
            if isinstance(k, tuple) and k[0].lower() == self.model.lower()
        ]

        if location in list_IAM_regions:
            return location

        # Second, it can be an ecoinvent region
        # with no native mapping
        if location in self.additional_mappings:

            if self.additional_mappings[location][self.model] in self.iam_regions:
                return self.additional_mappings[location][self.model]
            # likely a case of missing "EUR" region
            else:
                raise ValueError(f"Could not find equivalent for {location}.")

        # If not, then we look for IAM regions that contain it
        iam_location = [
            r[1]
            for r in self.geo.within(location)
            if r[0] == self.model.upper() and r[1] != "World"
        ]

        # If not, then we look for IAM regions that intersects with it
        if len(iam_location) == 0:
            iam_location = [
                r[1]
                for r in self.geo.intersects(location)
                if r[0] == self.model.upper() and r[1] != "World"
            ]

        # If not, then we look for IAM regions that are contained in it
        if len(iam_location) == 0:
            iam_location = [
                r[1]
                for r in self.geo.contained(location)
                if r[0] == self.model.upper() and r[1] != "World"
            ]

        if len(iam_location) == 0:
            print(
                "Cannot find the IAM location for {} from IAM model {}.".format(
                    location, self.model
                )
            )
            return "World"

        elif len(iam_location) == 1:
            return iam_location[0]
        else:

            if all(x in iam_location for x in ["NEU", "EUR"]):
                return "NEU"
            if all(x in iam_location for x in ["OAS", "JPN"]):
                return "JPN"
            if all(x in iam_location for x in ["CAZ", "USA"]):
                return "CAZ"
            if all(x in iam_location for x in ["OAS", "IND"]):
                return "IND"
            if all(x in iam_location for x in ["OAS", "CHA"]):
                return "CHA"
            if all(x in iam_location for x in ["OAS", "MEA"]):
                return "MEA"
            if all(x in iam_location for x in ["OAS", "REF"]):
                return "REF"
            if all(x in iam_location for x in ["OAS", "EUR"]):
                return "EUR"
            if all(x in iam_location for x in ["REF", "EUR"]):
                return "REF"
            if all(x in iam_location for x in ["MEA", "SSA"]):
                return "MEA"

            # more than one region is found
            print(f"More than one region found for {location}:{iam_location}")

    def iam_to_GAINS_region(self, location: str) -> str:
        """
        Regions defined in GAINS emission data follows REMIND naming
        convention, but those are different for other IAMs.
        :param location: IAM location
        :return: GAINS location
        """
        return self.iam_to_iam_mappings[self.model][location]["gains"]

    def iam_to_iam_region(self, location: str, to_iam: str) -> str:
        """
        When data is defined according to one IAM geography naming convention
        but needs to be used with another IAM.
        :param location: location to search the equivalent for
        :param: to_iam: the IAM to search the equivalent for
        :return: the equivalent location
        """

        return self.iam_to_iam_mappings[self.model][location][to_iam]
