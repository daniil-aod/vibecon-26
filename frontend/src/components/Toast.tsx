import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import Animated, { FadeInUp, FadeOutUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Lucide from "@react-native-vector-icons/lucide";
import { colors, fonts, radius, spacing } from "@/src/theme";

type Kind = "success" | "error" | "info";
type ToastT = { id: number; kind: Kind; msg: string };
const Ctx = createContext<(kind: Kind, msg: string) => void>(() => {});
export const useToast = () => {
  const show = useContext(Ctx);
  return { success: (m: string) => show("success", m), error: (m: string) => show("error", m), info: (m: string) => show("info", m) };
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [t, setT] = useState<ToastT | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const insets = useSafeAreaInsets();
  const show = useCallback((kind: Kind, msg: string) => {
    if (timer.current) clearTimeout(timer.current);
    setT({ id: Date.now(), kind, msg });
    timer.current = setTimeout(() => setT(null), 3500);
  }, []);
  const icon = t?.kind === "success" ? "circle-check" : t?.kind === "error" ? "triangle-alert" : "info";
  const tint = t?.kind === "success" ? colors.successGlow : t?.kind === "error" ? colors.warningGlow : colors.accentSoft;
  return (
    <Ctx.Provider value={show}>
      {children}
      {t && (
        <View pointerEvents="none" style={[styles.wrap, { top: insets.top + spacing.sm }]}>
          <Animated.View key={t.id} entering={FadeInUp} exiting={FadeOutUp} style={styles.toast} testID="toast-message">
            <Lucide name={icon} size={18} color={tint} />
            <Text style={styles.text}>{t.msg}</Text>
          </Animated.View>
        </View>
      )}
    </Ctx.Provider>
  );
}

const styles = StyleSheet.create({
  wrap: { position: "absolute", left: spacing.lg, right: spacing.lg, alignItems: "center" },
  toast: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.slate900,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderRadius: radius.lg, maxWidth: 480,
    shadowColor: colors.primary, shadowOpacity: 0.2, shadowRadius: 20, shadowOffset: { width: 0, height: 10 }, elevation: 6,
  },
  text: { color: colors.primaryForeground, fontFamily: fonts.bodyMedium, fontSize: 15, flexShrink: 1 },
});
