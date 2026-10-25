import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import Animated, { FadeInDown } from "react-native-reanimated";
import Lucide from "@react-native-vector-icons/lucide";
import { Logo } from "@/src/components/Logo";
import { PressButton } from "@/src/components/PressButton";
import { getTrip } from "@/src/lib/tracking";
import { parseLink } from "@/src/lib/api";
import { useI18n } from "@/src/lib/i18n";
import { LangToggle } from "@/src/components/LangToggle";
import { colors, fonts, radius, spacing } from "@/src/theme";

export default function Home() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { t: L } = useI18n();
  const [checking, setChecking] = useState(true);
  const [link, setLink] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getTrip().then((t) => {
      if (t) router.replace({ pathname: "/d/[token]", params: { token: t.token, api: t.api } });
      else setChecking(false);
    });
  }, [router]);

  const open = (value = link) => {
    const p = parseLink(value);
    if (!p) { setErr(L.linkBad); return; }
    setErr(null);
    router.push({ pathname: "/d/[token]", params: p.api ? { token: p.token, api: p.api } : { token: p.token } });
  };

  const paste = async () => {
    try {
      const t = await Clipboard.getStringAsync();
      if (t) { setLink(t); open(t); }
    } catch { setErr(L.clipFail); }
  };

  if (checking) return <View style={styles.center}><ActivityIndicator color={colors.slate900} /></View>;

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}><Logo /><LangToggle /></View>
      <KeyboardAwareScrollView bottomOffset={24} contentContainerStyle={[styles.body, { paddingBottom: insets.bottom + spacing.xl }]} keyboardShouldPersistTaps="handled">
        <Animated.View entering={FadeInDown.duration(400)}>
          <Text style={styles.kicker}>{L.homeKicker}</Text>
          <Text style={styles.h1} testID="home-title">{L.homeTitle}</Text>
          <Text style={styles.p}>{L.homeBody1}<Text style={styles.b}>{L.startTrip}</Text>{L.homeBody2}</Text>
        </Animated.View>

        <Animated.View entering={FadeInDown.delay(120).duration(400)} style={styles.card}>
          <View style={styles.step}><View style={styles.num}><Text style={styles.numT}>1</Text></View><Text style={styles.stepT}>{L.step1}</Text></View>
          <View style={styles.step}><View style={styles.num}><Text style={styles.numT}>2</Text></View><Text style={styles.stepT}>{L.step2}</Text></View>
          <View style={styles.step}><View style={styles.num}><Text style={styles.numT}>3</Text></View><Text style={styles.stepT}>{L.step3}</Text></View>
        </Animated.View>

        <Animated.View entering={FadeInDown.delay(220).duration(400)} style={styles.paste}>
          <Text style={styles.label}>{L.linkLabel}</Text>
          <TextInput
            testID="home-link-input"
            value={link}
            onChangeText={(v) => { setLink(v); setErr(null); }}
            placeholder={L.linkPlaceholder}
            placeholderTextColor={colors.slate400}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="go"
            onSubmitEditing={() => open()}
            style={styles.input}
          />
          {err && <Text style={styles.err} testID="home-link-error">{err}</Text>}
          <View style={styles.row}>
            <PressButton testID="home-paste-button" size="md" label={L.paste} icon="clipboard-paste" onPress={paste} bg={colors.surface} fg={colors.slate900} border={colors.slate900} style={{ flex: 1 }} />
            <PressButton testID="home-open-button" size="md" label={L.openLoad} icon="link" onPress={() => open()} bg={colors.primary} fg={colors.primaryForeground} style={{ flex: 1 }} />
          </View>
        </Animated.View>

        <View style={styles.note}>
          <Lucide name="lock" size={14} color={colors.mutedForeground} />
          <Text style={styles.noteT}>{L.privacy}</Text>
        </View>
      </KeyboardAwareScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.xl },
  kicker: { fontFamily: fonts.bodySemi, fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: colors.mutedForeground },
  h1: { fontFamily: fonts.display, fontSize: 30, color: colors.slate900, marginTop: spacing.xs, letterSpacing: -0.5 },
  p: { fontFamily: fonts.body, fontSize: 16, lineHeight: 24, color: colors.slate700, marginTop: spacing.sm },
  b: { fontFamily: fonts.bodySemi, color: colors.slate900 },
  card: { backgroundColor: colors.primary, borderRadius: radius.xxl, padding: spacing.xl, gap: spacing.lg },
  step: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  num: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center" },
  numT: { fontFamily: fonts.monoSemi, color: colors.primary, fontSize: 14 },
  stepT: { fontFamily: fonts.bodyMedium, color: colors.primaryForeground, fontSize: 16, flex: 1 },
  paste: { gap: spacing.sm },
  label: { fontFamily: fonts.bodySemi, fontSize: 15, color: colors.slate900 },
  input: { minHeight: 52, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, paddingHorizontal: spacing.lg, fontFamily: fonts.mono, fontSize: 14, color: colors.slate900, backgroundColor: colors.background },
  err: { fontFamily: fonts.body, fontSize: 14, color: colors.warningText },
  row: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xs },
  note: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  noteT: { fontFamily: fonts.body, fontSize: 13, color: colors.mutedForeground, flex: 1 },
});
