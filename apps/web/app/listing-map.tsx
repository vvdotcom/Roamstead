"use client";

import { importLibrary, setOptions } from "@googlemaps/js-api-loader";
import { MarkerClusterer } from "@googlemaps/markerclusterer";
import { AlertTriangle, MapPin, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Listing } from "@/lib/api";

const HCMC_CENTER = { lat: 10.7769, lng: 106.7009 };
const HCMC_BOUNDS = { south: 10.35, west: 106.3, north: 11.25, east: 107.15 };
const CACHE_KEY = "roamstead_google_geocodes_v1";
const CACHE_TTL_MS = 29 * 24 * 60 * 60 * 1000;
const WORKERS = 4;

type CachedLocation = { lat: number; lng: number; cachedAt: number };
type GeoCache = Record<string, CachedLocation>;

let configuredKey = "";

function geocodeQuery(listing: Listing) {
  const sourceLocation = listing.address?.trim() || listing.district;
  return `${sourceLocation}, Ho Chi Minh City, Vietnam`;
}

function insideHcmc(location: google.maps.LatLng) {
  const lat = location.lat();
  const lng = location.lng();
  return lat >= HCMC_BOUNDS.south && lat <= HCMC_BOUNDS.north && lng >= HCMC_BOUNDS.west && lng <= HCMC_BOUNDS.east;
}

function readCache(): GeoCache {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(CACHE_KEY) || "{}") as GeoCache;
    const now = Date.now();
    const active = Object.fromEntries(Object.entries(parsed).filter(([, value]) => now - value.cachedAt < CACHE_TTL_MS));
    if (Object.keys(active).length !== Object.keys(parsed).length) window.localStorage.setItem(CACHE_KEY, JSON.stringify(active));
    return active;
  } catch {
    return {};
  }
}

function writeCache(cache: GeoCache) {
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  } catch {
    // A private browser session can reject storage; the map still works without caching.
  }
}

async function locate(
  listing: Listing,
  geocoder: google.maps.Geocoder,
  cache: GeoCache,
): Promise<google.maps.LatLngLiteral | null> {
  const query = geocodeQuery(listing);
  const cached = cache[query];
  if (cached) return { lat: cached.lat, lng: cached.lng };

  const attempts = [query];
  const districtQuery = `${listing.district}, Ho Chi Minh City, Vietnam`;
  if (districtQuery !== query) attempts.push(districtQuery);

  for (const address of attempts) {
    try {
      const response = await geocoder.geocode({ address, bounds: HCMC_BOUNDS, region: "VN" });
      const match = response.results.find((result) => insideHcmc(result.geometry.location));
      if (!match) continue;
      const value = { lat: match.geometry.location.lat(), lng: match.geometry.location.lng(), cachedAt: Date.now() };
      cache[query] = value;
      writeCache(cache);
      return { lat: value.lat, lng: value.lng };
    } catch {
      // Try the district-level query before excluding this listing from the map.
    }
  }
  return null;
}

export default function ListingMap({
  listings,
  mobile,
  onListing,
}: {
  listings: Listing[];
  mobile: boolean;
  onListing: (listing: Listing) => void;
}) {
  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY?.trim() || "";
  const mapId = process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID?.trim() || "DEMO_MAP_ID";
  const mapElement = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<google.maps.Map | null>(null);
  const mapTypeRef = useRef<"roadmap" | "satellite">("roadmap");
  const [mapType, setMapType] = useState<"roadmap" | "satellite">("roadmap");
  const [status, setStatus] = useState<"MISSING_KEY" | "LOADING" | "READY" | "ERROR">(apiKey ? "LOADING" : "MISSING_KEY");

  function switchMapType(nextType: "roadmap" | "satellite") {
    mapTypeRef.current = nextType;
    setMapType(nextType);
    mapInstance.current?.setMapTypeId(nextType);
  }

  useEffect(() => {
    const hiddenOnMobile = window.matchMedia("(max-width: 700px)").matches && !mobile;
    if (!apiKey || !mapElement.current || hiddenOnMobile) return;
    let cancelled = false;
    let clusterer: MarkerClusterer | null = null;
    const markers: google.maps.marker.AdvancedMarkerElement[] = [];

    async function renderMap() {
      setStatus("LOADING");
      try {
        if (!configuredKey) {
          setOptions({ key: apiKey, v: "weekly", language: "en", region: "VN", authReferrerPolicy: "origin" });
          configuredKey = apiKey;
        }
        const [{ Map }, { LatLngBounds }, { Geocoder }, { AdvancedMarkerElement, PinElement }] = await Promise.all([
          importLibrary("maps"),
          importLibrary("core"),
          importLibrary("geocoding"),
          importLibrary("marker"),
        ]);
        if (cancelled || !mapElement.current) return;

        const map = new Map(mapElement.current, {
          center: HCMC_CENTER,
          zoom: 11,
          mapId,
          mapTypeId: mapTypeRef.current,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: true,
          clickableIcons: false,
          gestureHandling: "greedy",
        });
        mapInstance.current = map;
        const geocoder = new Geocoder();
        const cache = readCache();
        const bounds = new LatLngBounds();
        let cursor = 0;

        async function worker() {
          while (!cancelled) {
            const index = cursor++;
            if (index >= listings.length) return;
            const listing = listings[index];
            const position = await locate(listing, geocoder, cache);
            if (!position || cancelled) continue;
            const pin = new PinElement({
              background: "#EA6A1B",
              borderColor: "#ffffff",
              glyphColor: "#ffffff",
              glyphText: String(listing.fit_score),
              scale: 0.9,
            });
            const markerTitle = `${listing.title} · ${listing.district} · ${listing.fit_score} fit`;
            pin.setAttribute("aria-label", markerTitle);
            pin.setAttribute("role", "button");
            pin.tabIndex = 0;
            pin.addEventListener("click", () => onListing(listing));
            pin.addEventListener("keydown", (event) => {
              if (event.key === "Enter" || event.key === " ") onListing(listing);
            });
            const marker = new AdvancedMarkerElement({
              position,
              title: markerTitle,
              content: pin,
              gmpClickable: true,
              zIndex: listing.fit_score,
            });
            marker.addListener("gmp-click", () => onListing(listing));
            markers.push(marker);
            bounds.extend(position);
          }
        }

        await Promise.all(Array.from({ length: Math.min(WORKERS, Math.max(1, listings.length)) }, () => worker()));
        if (cancelled) return;
        clusterer = new MarkerClusterer({
          map,
          markers,
          renderer: {
            render({ count, position }) {
              const content = document.createElement("div");
              content.className = "property-map-cluster";
              content.textContent = String(count);
              content.setAttribute("aria-label", `${count} properties in this area`);
              return new AdvancedMarkerElement({
                position,
                content,
                title: `${count} properties in this area`,
                gmpClickable: true,
                zIndex: 1000 + count,
              });
            },
          },
        });
        if (markers.length > 1) map.fitBounds(bounds, 54);
        if (markers.length === 1) {
          map.setCenter(markers[0].position as google.maps.LatLngLiteral);
          map.setZoom(14);
        }
        setStatus("READY");
      } catch {
        if (!cancelled) setStatus("ERROR");
      }
    }

    void renderMap();
    return () => {
      cancelled = true;
      mapInstance.current = null;
      clusterer?.clearMarkers();
      markers.forEach((marker) => { marker.map = null; });
    };
  }, [apiKey, listings, mapId, mobile, onListing]);

  if (!apiKey) {
    return (
      <section className={`listing-map-panel ${mobile ? "mobile-map" : ""}`} aria-label="Google Map setup for matching properties">
        <div className="map-config-card">
          <span><MapPin size={24} /></span>
          <small>Google Maps integration ready</small>
          <h2>Add your browser map key</h2>
          <p>Set <code>NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code> in <code>apps/web/.env.local</code>, then restart the web app.</p>
          <div><ShieldCheck size={15} /> Restrict the key to Maps JavaScript API, Geocoding API, and your website origins.</div>
        </div>
      </section>
    );
  }

  return (
    <section className={`listing-map-panel ${mobile ? "mobile-map" : ""}`} aria-label={`Google Map of ${listings.length} matching properties`}>
      <div ref={mapElement} className="google-listing-map" />
      <div className="map-type-toggle" role="group" aria-label="Map type">
        <button type="button" className={mapType === "roadmap" ? "active" : ""} aria-pressed={mapType === "roadmap"} onClick={() => switchMapType("roadmap")}>Normal</button>
        <button type="button" className={mapType === "satellite" ? "active" : ""} aria-pressed={mapType === "satellite"} onClick={() => switchMapType("satellite")}>Satellite</button>
      </div>
      {status === "LOADING" && <div className="map-loading-card"><span /><b>Locating source addresses…</b><small>Coordinates are cached for up to 29 days.</small></div>}
      {status === "ERROR" && <div className="map-error-card"><AlertTriangle size={18} /><b>Google Maps could not load</b><small>Check the key, billing, referrer restrictions, and enabled APIs.</small></div>}
    </section>
  );
}
