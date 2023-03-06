"""
Integrates projections regarding direct air capture and storage.
"""

import copy

import numpy as np
import yaml

from .transformation import (
    BaseTransformation,
    IAMDataCollection,
    InventorySet,
    List,
    relink_technosphere_exchanges,
    uuid,
    ws,
    wurst,
)
from .utils import DATA_DIR, write_log

HEAT_SOURCES = DATA_DIR / "fuels" / "heat_sources_map.yml"


def fetch_mapping(filepath: str) -> dict:
    """Returns a dictionary from a YML file"""

    with open(filepath, "r", encoding="utf-8") as stream:
        mapping = yaml.safe_load(stream)
    return mapping


class DirectAirCapture(BaseTransformation):
    """
    Class that modifies DAC and DACCS inventories and markets
    in ecoinvent based on IAM output data.
    """

    def __init__(
        self,
        database: List[dict],
        iam_data: IAMDataCollection,
        model: str,
        pathway: str,
        year: int,
        version: str,
    ):
        super().__init__(database, iam_data, model, pathway, year)
        # ecoinvent version
        self.version = version
        mapping = InventorySet(self.database)
        self.dac_plants = mapping.generate_daccs_map()
        self.carbon_storage = mapping.generate_carbon_storage_map()
        # dictionary to store mapping results, to avoid redundant effort
        self.cached_suppliers = {}

    def generate_dac_activities(self) -> None:
        """
        Generates regional variants of the direct air capture process with varying heat sources.

        This function fetches the original datasets for the direct air capture process and creates regional variants
        with different heat sources. The function loops through the heat sources defined in the `HEAT_SOURCES` mapping,
        modifies the original datasets to include the heat source, and adds the modified datasets to the database.

        """
        print("Generate region-specific direct air capture processes.")

        # get original dataset
        for ds_list in self.carbon_storage.values():
            for ds_name in ds_list:
                new_ds = self.fetch_proxies(
                    name=ds_name,
                    ref_prod="carbon dioxide, stored",
                )

                # delete original
                self.database = [x for x in self.database if x["name"] != ds_name]

                for _, dataset in new_ds.items():
                    self.cache, dataset = relink_technosphere_exchanges(
                        dataset,
                        self.database,
                        self.model,
                        cache=self.cache,
                    )

                self.database.extend(new_ds.values())

                # Add created dataset to `self.list_datasets`
                self.list_datasets.extend(
                    [
                        (
                            act["name"],
                            act["reference product"],
                            act["location"],
                        )
                        for act in new_ds.values()
                    ]
                )

        # define heat sources
        heat_map_ds = fetch_mapping(HEAT_SOURCES)

        # get original dataset
        for technology, ds_list in self.dac_plants.items():
            for ds_name in ds_list:

                original_ds = self.fetch_proxies(
                    name=ds_name, ref_prod="carbon dioxide", relink=False
                )

                # delete original
                self.database = [x for x in self.database if x["name"] != ds_name]

                # loop through heat sources
                for heat_type, activities in heat_map_ds.items():
                    new_ds = copy.deepcopy(original_ds)
                    for _, dataset in new_ds.items():

                        dataset["name"] += f", with {heat_type}, and grid electricity"
                        dataset["code"] = str(uuid.uuid4().hex)
                        dataset["comment"] += activities["description"]

                        for exc in ws.production(dataset):
                            exc["name"] = dataset["name"]
                            if "input" in exc:
                                del exc["input"]

                        for exc in ws.technosphere(dataset):
                            if "heat" in exc["name"]:
                                exc["name"] = activities["name"]
                                exc["product"] = activities["reference product"]
                                exc["location"] = "RoW"

                                if heat_type == "heat pump heat":
                                    exc["unit"] = "kilowatt hour"
                                    exc["amount"] *= 1 / (2.9 * 3.6)

                        self.cache, dataset = relink_technosphere_exchanges(
                            dataset,
                            self.database,
                            self.model,
                            cache=self.cache,
                        )

                    # adjust efficiency, if needed
                    new_ds = self.adjust_dac_efficiency(new_ds, technology)

                    self.database.extend(new_ds.values())

                    # add to log
                    for datasets in list(new_ds.values()):
                        write_log(
                            "direct air capture",
                            "created",
                            datasets,
                            self.model,
                            self.scenario,
                            self.year,
                        )

                    # Add created dataset to `self.list_datasets`
                    self.list_datasets.extend(
                        [
                            (
                                act["name"],
                                act["reference product"],
                                act["location"],
                            )
                            for act in new_ds.values()
                        ]
                    )

    def adjust_dac_efficiency(self, datasets, technology):
        """
        Fetch the cumulated deployment of DAC from IAM file.
        Apply a learning rate (2.5%) -- see Qiu et al., 2022.
        """

        # learning rates for operation-related expenditures
        # (thermal and electrical energy)
        learning_rates_operation = {
            "dac_solvent": 0.025,
            "dac_sorbent": 0.025,
            "daccs_solvent": 0.025,
            "daccs_sorbent": 0.025,
        }

        # learning rates for
        # infrastructure-related expenditures
        learning_rates_infra = {
            "dac_solvent": 0.1,
            "dac_sorbent": 0.15,
            "daccs_solvent": 0.1,
            "daccs_sorbent": 0.15,
        }

        theoretical_min_operation = {
            "dac_solvent": 0.5,
            "dac_sorbent": 0.5,
            "daccs_solvent": 0.5,
            "daccs_sorbent": 0.5,
        }

        theoretical_min_infra = {
            "dac_solvent": 0.44,
            "dac_sorbent": 0.18,
            "daccs_solvent": 0.44,
            "daccs_sorbent": 0.18,
        }

        # fetch cumulated deployment of DAC from IAM file
        if "dac_solvent" in self.iam_data.production_volumes.variables.values:
            for region, dataset in datasets.items():

                cumulated_deployment = (
                    np.clip(
                        self.iam_data.production_volumes.sel(
                            variables="dac_solvent",
                        )
                        .interp(year=self.year)
                        .sum(dim="region")
                        .values.item()
                        * -1,
                        1e-3,
                        None,
                    )
                    / 2
                )  # divide by 2,
                # as we assume sorbent and solvent are deployed equally

                initial_deployment = (
                    np.clip(
                        self.iam_data.production_volumes.sel(
                            variables="dac_solvent", year=2020
                        )
                        .sum(dim="region")
                        .values.item()
                        * -1,
                        1e-3,
                        None,
                    )
                    / 2
                )  # divide by 2,
                # as we assume sorbent and solvent are deployed equally

                # the learning rate is applied per doubling
                # of the cumulative deployment
                # relative to 2020

                scaling_factor_operation = (
                    1 - theoretical_min_operation[technology]
                ) * np.power(
                    (1 - learning_rates_operation[technology]),
                    np.log2(cumulated_deployment / initial_deployment),
                ) + theoretical_min_operation[
                    technology
                ]

                scaling_factor_infra = (
                    1 - theoretical_min_infra[technology]
                ) * np.power(
                    (1 - learning_rates_infra[technology]),
                    np.log2(cumulated_deployment / initial_deployment),
                ) + theoretical_min_infra[
                    technology
                ]

                # Scale down the energy exchanges using the scaling factor
                wurst.change_exchanges_by_constant_factor(
                    dataset,
                    scaling_factor_operation,
                    technosphere_filters=[
                        ws.either(
                            *[ws.contains("name", x) for x in ["heat", "electricity"]]
                        )
                    ],
                    biosphere_filters=[ws.exclude(ws.contains("type", "biosphere"))],
                )

                # add in comments the scaling factor applied
                dataset["comment"] += (
                    f" Operation-related expenditures have been "
                    f"reduced by: {int((1 - scaling_factor_operation) * 100)}%."
                )

                # Scale down the infra and material exchanges using the scaling factor
                wurst.change_exchanges_by_constant_factor(
                    dataset,
                    scaling_factor_infra,
                    technosphere_filters=[
                        ws.exclude(
                            ws.either(
                                *[
                                    ws.contains("name", x)
                                    for x in ["heat", "electricity", "storage"]
                                ]
                            )
                        )
                    ],
                    biosphere_filters=[ws.exclude(ws.contains("type", "biosphere"))],
                )

                # add in comments the scaling factor applied
                dataset["comment"] += (
                    f" Infrastructure-related expenditures have been "
                    f"reduced by: {int((1 - scaling_factor_infra) * 100)}%."
                )

        return datasets
