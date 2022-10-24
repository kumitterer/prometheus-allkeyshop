from prometheus_client import start_http_server, Gauge

from configparser import ConfigParser
from pathlib import Path
from urllib.request import urlopen, Request
from html.parser import HTMLParser
from typing import List, Tuple, Optional

import re
import json
import time


class AllKeyShop:
    PLATFORM_PC = "cd-key"
    PLATFORM_PS5 = "ps5"
    PLATFORM_PS4 = "ps4"
    PLATFORM_XB1 = "xbox-one"
    PLATFORM_XBSX = "xbox-series-x"
    PLATFORM_SWITCH = "nintendo-switch"

    class ProductParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.result: int

        def handle_starttag(self, tag: str, attrs: List[Tuple[str, str]]):
            for attr in attrs:
                if attr[0] == "data-product-id":
                    try:
                        self.result = int(attr[1])
                    except:
                        pass

    class HTTPRequest(Request):
        def __init__(self, url: str, *args, **kwargs):
            super().__init__(url, *args, **kwargs)
            self.headers["user-agent"] = "allkeyshop.com prometheus exporter (https://kumig.it/kumitterer/prometheus-allkeyshop)"

    class ProductPageRequest(HTTPRequest):
        @staticmethod
        def to_slug(string: str) -> str:

            # Shamelessly stolen from https://www.30secondsofcode.org/python/s/slugify
            # Website, name & logo © 2017-2022 30 seconds of code (https://github.com/30-seconds)
            # Individual snippets licensed under CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/)

            string = string.lower().strip()
            string = re.sub(r'[^\w\s-]', '', string)
            string = re.sub(r'[\s_-]+', '-', string)
            string = re.sub(r'^-+|-+$', '', string)

            return string

        def __init__(self, product: str, platform: str, *args, **kwargs):
            slug = self.__class__.to_slug(product)

            if platform == "pc":
                platform = AllKeyShop.PLATFORM_PC

            url = f"https://www.allkeyshop.com/blog/buy-{slug}-{platform}-compare-prices/"

            super().__init__(url, *args, **kwargs)

    class OffersRequest(HTTPRequest):
        def __init__(self, product: int, *args, currency: str, **kwargs):
            region: str = kwargs.pop("region", "")
            edition: str = kwargs.pop("edition", "")
            moreq: str = kwargs.pop("moreq", "")

            url = f"https://www.allkeyshop.com/blog/wp-admin/admin-ajax.php?action=get_offers&product={product}&currency={currency}&region={region}&edition={edition}&moreq={moreq}&use_beta_offers_display=1"

            super().__init__(url, *args, **kwargs)

    def __init__(self, product: int | str, platform: Optional[str] = None, **kwargs):
        self.product: int
        self.kwargs: dict = kwargs

        if isinstance(product, int):
            self.product = product
        else:
            assert platform
            self.product = self.__class__.resolve_product(product, platform)

    @classmethod
    def resolve_product(cls, product: str, platform: str) -> int:
        content = urlopen(cls.ProductPageRequest(product, platform))
        html = content.read().decode()

        parser = cls.ProductParser()
        parser.feed(html)

        assert parser.result
        return parser.result

    def get_offers(self) -> dict:
        content = urlopen(self.__class__.OffersRequest(
            self.product, **self.kwargs))
        raw = content.read()

        content = json.loads(raw)
        assert content["success"]
        return content["offers"]


config = ConfigParser()
config.read(Path(__file__).parent / "settings.ini")

gauges: List[Tuple[Gauge, AllKeyShop]] = list()

if config.has_section("DEFAULT"):
    defaults = config["DEFAULT"]
else:
    defaults = dict()

for section, settings in filter(lambda x: x[0] != "DEFAULT", config.items()):
    try:
        currency: int
        assert (currency := settings.get(
            "Currency", fallback=defaults.get("Currency")).lower())

        region: str = settings.get(
            "Region", fallback=defaults.get("Region", ""))
        edition: str = settings.get("Edition", fallback="")

        product: str | int
        platform: Optional[str]
        name: str

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
                product, platform, currency=currency, region=region, edition=edition)

        gauge = Gauge(
            f"allkeyshop_{AllKeyShop.ProductPageRequest.to_slug(name).replace('-', '_')}_{currency}", "Best price for {name}")
        gauges.append((gauge, aks))

    except Exception as e:
        print(f"Error setting up gauge for section {section}: {e}")


start_http_server(8090)

while True:
    for gauge, aks in gauges:
        try:
            offers: List[dict] = aks.get_offers()
            available_offers: List[dict] = filter(
                lambda x: x["stock"] == "InStock", offers)
            store: Optional[str]

            if (store := settings.get("Store", fallback=defaults.get("Store", ""))):
                available_offers: List[dict] = filter(
                    lambda x: x["platform"] == store, available_offers)

            best_offer: dict = min(
                available_offers, key=lambda x: x["price"][currency]["price"])
            gauge.set(best_offer["price"][currency]["price"])
        except Exception as e:
            print(f"Error updating gauge value for {gauge._name}: {e}")

    time.sleep(60)
