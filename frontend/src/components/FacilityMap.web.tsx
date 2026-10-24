import { StyleSheet, Text, View } from "react-native";
import Lucide from "@react-native-vector-icons/lucide";
import { colors, fonts, radius, spacing } from "@/src/theme";
import type { Fix, Stop } from "@/src/lib/api";

// Web preview placeholder — the live map renders inside the phone app.
export function FacilityMap({ stop, truck, height = 200, testID }: { stop: Stop; truck: Fix | null; height?: number; testID: string }) {
  return (
    <View style={[styles.wrap, { height }]} testID={testID}>
      <Lucide name="map-pin" size={28} color={colors.accent} />
      <Text style={styles.t}>{stop.facility_name}</Text>
      <Text style={styles.s}>{truck ? `You: ${truck.lat.toFixed(5)}, ${truck.lng.toFixed(5)}` : "Live map shows in the phone app"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.muted, alignItems: "center", justifyContent: "center", gap: spacing.xs, padding: spacing.lg },
  t: { fontFamily: fonts.bodySemi, fontSize: 15, color: colors.slate900 },
  s: { fontFamily: fonts.mono, fontSize: 12, color: colors.mutedForeground },
});
