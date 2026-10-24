import { StyleSheet, Text, View } from "react-native";
import Lucide from "@react-native-vector-icons/lucide";
import { colors, fonts, radius } from "@/src/theme";

export function Logo() {
  return (
    <View style={styles.row} testID="app-logo">
      <View style={styles.mark}><Lucide name="clock-3" size={18} color={colors.accentSoft} /></View>
      <Text style={styles.name}>DockClock</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  mark: { width: 32, height: 32, borderRadius: radius.md, backgroundColor: colors.slate900, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: fonts.display, fontSize: 18, color: colors.slate900, letterSpacing: -0.3 },
});
