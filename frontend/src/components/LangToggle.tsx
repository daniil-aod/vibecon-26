import { Pressable, StyleSheet, Text, View } from "react-native";
import { useI18n, Lang } from "@/src/lib/i18n";
import { colors, fonts, radius } from "@/src/theme";

export function LangToggle() {
  const { lang, setLang } = useI18n();
  return (
    <View style={styles.wrap} testID="lang-toggle">
      {(["en", "es"] as Lang[]).map((l) => (
        <Pressable key={l} testID={`lang-${l}-button`} onPress={() => setLang(l)} hitSlop={6}
          style={[styles.opt, lang === l && styles.on]} accessibilityRole="button" accessibilityState={{ selected: lang === l }}>
          <Text style={[styles.t, lang === l && styles.tOn]}>{l.toUpperCase()}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, padding: 2 },
  opt: { minWidth: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  on: { backgroundColor: colors.slate900 },
  t: { fontFamily: fonts.monoSemi, fontSize: 12, color: colors.mutedForeground },
  tOn: { color: colors.primaryForeground },
});
