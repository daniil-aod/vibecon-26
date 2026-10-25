import { StyleSheet, Text, View } from "react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { useI18n } from "@/src/lib/i18n";
import { fmtClock, hrs } from "@/src/lib/format";
import type { Stop } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/theme";

const mins = (s: Stop) => (s.arrived_at && s.departed_at ? (new Date(s.departed_at).getTime() - new Date(s.arrived_at).getTime()) / 60000 : 0);
const day = (iso?: string | null) => (iso ? `${new Date(iso).getMonth() + 1}/${new Date(iso).getDate()} ` : "");

/** Recap shown to the driver after delivery: each stop's in/out times and wait time. */
export function TripSummary({ stops }: { stops: Stop[] }) {
  const { t: L } = useI18n();
  const total = stops.reduce((a, s) => a + mins(s), 0);
  return (
    <Animated.View entering={FadeInDown.duration(350)} style={styles.card} testID="trip-summary">
      <Text style={styles.k}>{L.tripSummary}</Text>
      {stops.map((s, i) => (
        <View key={s.id} style={[styles.row, i > 0 && styles.divider]} testID={`trip-summary-stop-${i}`}>
          <Text style={styles.name} numberOfLines={1}>{i + 1}. {s.facility_name}</Text>
          <View style={styles.cols}>
            <View style={styles.col}><Text style={styles.lbl}>{L.inAt}</Text><Text style={styles.val}>{day(s.arrived_at)}{fmtClock(s.arrived_at)}</Text></View>
            <View style={styles.col}><Text style={styles.lbl}>{L.outAt}</Text><Text style={styles.val}>{day(s.departed_at)}{fmtClock(s.departed_at)}</Text></View>
            <View style={styles.col}><Text style={styles.lbl}>{L.waitTime}</Text><Text style={[styles.val, styles.wait]}>{s.arrived_at ? hrs(mins(s)) : "—"}</Text></View>
          </View>
        </View>
      ))}
      <View style={styles.total} testID="trip-summary-total">
        <Text style={styles.totalL}>{L.totalWait}</Text>
        <Text style={styles.totalV}>{hrs(total)}</Text>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: { marginTop: spacing.xl, backgroundColor: colors.primary, borderRadius: radius.xxl, padding: spacing.xl },
  k: { fontFamily: fonts.bodySemi, fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: colors.accentSoft, marginBottom: spacing.sm },
  row: { paddingVertical: spacing.md },
  divider: { borderTopWidth: 1, borderTopColor: colors.slate700 },
  name: { fontFamily: fonts.bodySemi, fontSize: 16, color: colors.primaryForeground },
  cols: { flexDirection: "row", marginTop: spacing.sm },
  col: { flex: 1 },
  lbl: { fontFamily: fonts.body, fontSize: 12, color: colors.slate400 },
  val: { fontFamily: fonts.monoSemi, fontSize: 15, color: colors.primaryForeground, marginTop: 2 },
  wait: { color: colors.warningGlow },
  total: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", borderTopWidth: 1, borderTopColor: colors.slate700, paddingTop: spacing.md, marginTop: spacing.xs },
  totalL: { fontFamily: fonts.bodySemi, fontSize: 15, color: colors.primaryForeground },
  totalV: { fontFamily: fonts.monoSemi, fontSize: 20, color: colors.accentSoft },
});
