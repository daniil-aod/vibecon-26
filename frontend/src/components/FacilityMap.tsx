import { useEffect, useMemo, useRef } from "react";
import { StyleSheet, View } from "react-native";
import { WebView } from "react-native-webview";
import { colors, radius } from "@/src/theme";
import type { Fix, Stop } from "@/src/lib/api";

// Same OpenStreetMap/Leaflet map as the web app, rendered in a WebView (no map API key needed).
export function FacilityMap({ stop, truck, height = 200, testID }: { stop: Stop; truck: Fix | null; height?: number; testID: string }) {
  const ref = useRef<WebView>(null);
  const html = useMemo(() => {
    const lat = stop.lat ?? 39.5, lng = stop.lng ?? -98.35, r = stop.radius_m || 45;
    return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{margin:0;height:100%;background:#eef2f6}.leaflet-control-attribution{font-size:9px}</style></head>
<body><div id="m"></div><script>
var map=L.map('m',{zoomControl:false,attributionControl:true}).setView([${lat},${lng}],${stop.lat != null ? 15 : 4});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);
${stop.lat != null ? `L.circle([${lat},${lng}],{radius:${r},color:'${colors.accent}',weight:2,fillOpacity:0.12}).addTo(map);
L.circleMarker([${lat},${lng}],{radius:7,color:'${colors.slate900}',fillColor:'${colors.slate900}',fillOpacity:1}).addTo(map);` : ""}
var truck=null;
window.setTruck=function(a,b){var ll=[a,b];if(!truck){truck=L.circleMarker(ll,{radius:8,color:'#ffffff',weight:3,fillColor:'${colors.info}',fillOpacity:1}).addTo(map);
${stop.lat != null ? `map.fitBounds(L.latLngBounds([ll,[${lat},${lng}]]).pad(0.3),{maxZoom:16});` : "map.setView(ll,15);"}}else truck.setLatLng(ll);};
</script></body></html>`;
  }, [stop.lat, stop.lng, stop.radius_m]);

  useEffect(() => {
    if (truck) ref.current?.injectJavaScript(`window.setTruck&&window.setTruck(${truck.lat},${truck.lng});true;`);
  }, [truck]);

  return (
    <View style={[styles.wrap, { height }]} testID={testID}>
      <WebView
        ref={ref}
        source={{ html }}
        originWhitelist={["*"]}
        scrollEnabled={false}
        onLoadEnd={() => truck && ref.current?.injectJavaScript(`window.setTruck(${truck.lat},${truck.lng});true;`)}
        style={styles.web}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { borderRadius: radius.lg, overflow: "hidden", borderWidth: 1, borderColor: colors.border, backgroundColor: colors.muted },
  web: { flex: 1, backgroundColor: colors.muted },
});
