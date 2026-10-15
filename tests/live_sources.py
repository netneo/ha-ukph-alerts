"""Live smoke test of every source: PYTHONPATH=. python tests/live_sources.py"""
import asyncio
import aiohttp
from custom_components.ukph_alerts.api import UkphApi, guess_ukhsa_region, irish_grid_to_wgs84


async def main():
    async with aiohttp.ClientSession() as s:
        api = UkphApi(s)
        t = await api.threat(); print("THREAT", t["level"], "NI:", t["ni_level"], "|", t["updated"])
        g = await api.grid(); print("GRID", g["status"], "active:", [n["summary"] for n in g["active"]], "recent:", [n["summary"] for n in g["recent"][:3]])
        for name, (lat, lon) in {"Abbotsley": (52.2, -0.2), "London": (51.5, -0.12), "Perth": (56.4, -3.43),
                                 "Belfast": (54.6, -5.93), "Cardiff": (51.48, -3.18), "Newcastle": (54.97, -1.61)}.items():
            r = guess_ukhsa_region(lat, lon)
            h = await api.health("cold", r) if r else None
            print("UKHSA", name, r, h and (h["level"], h["region"]))
        print("SEPA floods near Perth 25km:", len(await api.floods(56.4, -3.43, 25, scotland=True)))
        sr = await api.sepa_rivers(56.4, -3.43, 15); print("SEPA rivers near Perth:", [(x["station"], x["status"], x["distance_km"]) for x in sr][:5])
        for name, nets, (lat, lon), rad in [("Abbotsley", ["ukpn"], (52.2, -0.2), 25), ("Sheffield", ["npg"], (53.38, -1.47), 25),
                                            ("Bristol", ["nged", "ssen"], (51.45, -2.59), 40), ("Perth", ["ssen"], (56.4, -3.43), 60),
                                            ("Belfast", ["nie"], (54.6, -5.93), 15), ("Exeter", ["nged"], (50.72, -3.53), 10)]:
            cuts = await api.power_cuts(nets, lat, lon, rad)
            print(f"POWER {name} {nets} {rad}km:", len(cuts), [(c['network'][:8], c['distance_km'], c['customers'], c['planned']) for c in cuts[:4]])
    print("Belfast grid check:", irish_grid_to_wgs84(333500, 373500), "(expect ~54.60, -5.93)")

asyncio.run(main())
