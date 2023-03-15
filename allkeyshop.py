#!/usr/bin/env python3

###################################################################
# allkeyshop.py - Prometheus exporter for allkeyshop.com
# 2022 - 2023 kumitterer (https://kumig.it/kumitterer)
#
# This program is free software under the terms of the MIT License,
# except where otherwise noted.
###################################################################

from prometheus_client import start_http_server, Gauge, CollectorRegistry

from configparser import ConfigParser
from argparse import ArgumentParser
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from html.parser import HTMLParser
from typing import List, Tuple, Optional

import re
import json
import time


class AllKeyShop:
    """A class abstracting interaction with allkeyshop.com
    """

    # Define AllKeyShop's internal names for platforms as they are used in URLs

    PLATFORM_PC = "cd-key"
    PLATFORM_PS5 = "ps5"
    PLATFORM_PS4 = "ps4"
    PLATFORM_XB1 = "xbox-one"
    PLATFORM_XBSX = "xbox-series-x"
    PLATFORM_SWITCH = "nintendo-switch"

    class ProductParser(HTMLParser):
        """A parser for the product page of allkeyshop.com
        Yields the product ID of the product in its result attribute
        """

        def __init__(self):
            super().__init__()
            self.reset()
            self.result: int

        def handle_starttag(self, tag: str, attrs: List[Tuple[str, str]]):
            # Basically, we're looking for a tag with the "data-product-id"
            # attribute and parse the value of that attribute as an integer

            for attr in attrs:
                if attr[0] == "data-product-id":
                    try:
                        self.result = int(attr[1])
                    except (ValueError, IndexError):
                        # Not sure if this can even happen,
                        # but better safe than sorry

                        pass
                    except Exception as e:
                        # If this happens, something is seriously wrong

                        print(f"Error while parsing product ID: {e}")

    class HTTPRequest(Request):
        """Custom HTTP request class with a custom user agent
        """

        def __init__(self, url: str, *args, **kwargs):
            super().__init__(url, *args, **kwargs)
            self.headers["user-agent"] = "allkeyshop.com prometheus exporter (https://kumig.it/kumitterer/prometheus-allkeyshop)"

    class ProductPageRequest(HTTPRequest):
        """Class for generating requests to the product page of allkeyshop.com
        """
        @staticmethod
        def to_slug(string: str) -> str:
            """Helper function for generating slugs from strings

            Shamelessly stolen from https://www.30secondsofcode.org/python/s/slugify
            Website, name & logo © 2017-2022 30 seconds of code (https://github.com/30-seconds)
            Individual snippets licensed under CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/)

            Args:
                string (str): The string to generate a slug from

            Returns:
                str: The generated slug
            """

            string = string.lower().strip()
            string = re.sub(r'[^\w\s-]', '', string)
            string = re.sub(r'[\s_-]+', '-', string)
            string = re.sub(r'^-+|-+$', '', string)

            return string

        def __init__(self, product: str, platform: str, *args, **kwargs):

            # Get slug to use in URL

            slug = self.__class__.to_slug(product)

            # Allow "pc" as shorthand platform name for PCs

            if platform == "pc":
                platform = AllKeyShop.PLATFORM_PC

            # Set request URL

            url = f"https://www.allkeyshop.com/blog/buy-{slug}-{platform}-compare-prices/"
            super().__init__(url, *args, **kwargs)

    class OffersRequest(HTTPRequest):
        """Class for generating requests to the offers API of allkeyshop.com
        """

        def __init__(self, product: int, *args, currency: str, **kwargs):
            """Initializes the request

            Args:
                product (int): Product ID of the product to get offers for
                currency (str): Currency to get offers in (e.g. "eur")
                region (str, optional): Region to get offers for (e.g. "eu"). Defaults to "".
                edition (str, optional): Edition to get offers for (e.g. "standard"). Defaults to "".
                moreq (str, optional): Additional query parameters. Defaults to "".
            """
            region: str = kwargs.pop("region", "")
            edition: str = kwargs.pop("edition", "")
            moreq: str = kwargs.pop("moreq", "")

            url = f"https://www.allkeyshop.com/blog/wp-admin/admin-ajax.php?action=get_offers&product={product}&currency={currency}&region={region}&edition={edition}&moreq={moreq}&use_beta_offers_display=1"

            super().__init__(url, *args, **kwargs)

    def __init__(self, product: int | str, platform: Optional[str] = None, **kwargs):
        """Initializes the AllKeyShop object

        Args:
            product (int | str): Product ID or name of the product to get offers for
            platform (Optional[str], optional): Platform to get offers for, if a product name is passed. Defaults to None.
        """
        self.product: int
        self.kwargs: dict = kwargs

        if isinstance(product, int):
            # Product ID is already known - no need to resolve it
            self.product = product
        else:
            # Resolve product ID from product name and platform
            assert platform, "Platform must be specified if product name is passed"
            self.product = self.__class__.resolve_product(product, platform)

    @classmethod
    def resolve_product(cls, product: str, platform: str) -> int:
        """Resolves a product ID from a product name and platform

        Args:
            product (str): Name of the product to resolve
            platform (str): Platform to get the product ID for

        Returns:
            int: Product ID matching the given product name and platform
        """

        # Get product page

        content = urlopen(cls.ProductPageRequest(product, platform))
        html = content.read().decode()

        # Pass the content to the custom HTML parser

        parser = cls.ProductParser()
        parser.feed(html)

        # Return the result, or raise an exception if no result was found

        assert parser.result, f"Could not resolve product ID for product {product} on platform {platform}"
        return parser.result

    def get_offers(self) -> dict:
        """Gets all offers for the product

        Returns:
            dict: Offers for the product
        """

        # Get offers

        content = urlopen(self.__class__.OffersRequest(
            self.product, **self.kwargs))
        raw = content.read()

        content = json.loads(raw)

        # Return the offers, or raise an exception if the request failed

        assert content["success"], "Something went wrong while getting offers"
        return content["offers"]


def main():
    # Parse command line arguments

    parser = ArgumentParser(
        description="Prometheus exporter for allkeyshop.com")
    parser.add_argument("-c", "--config", type=Path, default=Path(__file__).parent /
                        "settings.ini", help="Path to config file (default: settings.ini in script directory)")
    parser.add_argument("-p", "--port", type=int, default=8090,
                        help="Port to listen on (default: 8090)")
    parser.add_argument("-a", "--address", type=str, default="0.0.0.0",
                        help="Address to listen on (default: 0.0.0.0)")
    args = parser.parse_args()

    # Read configuration file

    config = ConfigParser()
    config.read(args.config)

    if config.has_section("DEFAULT"):
        defaults = config["DEFAULT"]
    else:
        defaults = dict()

    # Initialize a custom CollectorRegistry so we don't get the default metrics

    registry = CollectorRegistry()

    # Initialize Gauge

    gauge = Gauge(
        f"allkeyshop_best_price", f"Best price for a product on allkeyshop.com",
        ["product_name", "currency"], registry=registry)

    # Initialize products

    products: List[Tuple[AllKeyShop, str, str]] = list()

    for section, settings in filter(lambda x: x[0] != "DEFAULT", config.items()):
        try:
            # Assert that we know the currency we want to use

            currency: str
            assert (currency := settings.get(
                "Currency", fallback=defaults.get("Currency"))), "Currency not set for section {section}"
            currency = currency.lower()

            # Check if we need a specific region or edition

            region: str = settings.get(
                "Region", fallback=defaults.get("Region", ""))
            edition: str = settings.get("Edition", fallback="")

            product: str | int
            platform: Optional[str]
            name: str

            # Initialize AllKeyShop object

            try:
                product = int(section)
                name = settings.get("Name", fallback=section)
                aks: AllKeyShop = AllKeyShop(
                    product, currency=currency, region=region, edition=edition)

            except ValueError:
                product = name = section
                platform = settings.get(
                    "Platform", fallback=defaults.get("Platform"))
                assert platform
                aks: AllKeyShop = AllKeyShop(
                    product, platform, currency=currency,
                    region=region, edition=edition)

            # Finally, add the product to the list

            products.append((aks, name, currency))

        # If something goes wrong at this point, we assume that there is a
        # problem with the configuration file and exit

        except HTTPError as e:
            print(f"Error calling URL {e.url} for section {section}: {e}")
            exit(1)
        except Exception as e:
            print(f"Error setting up gauge for section {section}: {e}")
            exit(1)

    # Self-explanatory line, no?

    start_http_server(args.port, args.address, registry)

    # Start updating the prices

    while True:
        for aks, name, currency in products:
            try:
                # Get all offers and filter out the ones that are not in stock

                offers: List[dict] = aks.get_offers()
                available_offers: List[dict] = filter(
                    lambda x: x["stock"] == "InStock", offers)

                # If we have a store preference, filter out the offers that are
                # not from that store

                store: Optional[str]

                if (store := settings.get("Store", fallback=defaults.get("Store", ""))):
                    available_offers: List[dict] = filter(
                        lambda x: x["platform"] == store, available_offers)

                # Get the best offer and update the gauge

                best_offer: dict = min(
                    available_offers, key=lambda x: x["price"][currency]["price"])
                gauge.labels(product_name=name, currency=currency).set(
                    best_offer["price"][currency]["price"])

            # If something goes wrong at this stage, we assume that there is just
            # a problem with our connectivity or the website itself and continue

            except Exception as e:
                print(f"Error updating gauge value for {gauge._name}: {e}")

        # Finally, wait for a minute before updating the prices again

        time.sleep(60)


if __name__ == "__main__":
    main()
