import React from "react";
import { ActivityIndicator, Pressable, StyleProp, StyleSheet, Text, TextStyle, ViewStyle } from "react-native";
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from "react-native-reanimated";
import Lucide, { LucideIconName } from "@react-native-vector-icons/lucide";
import { fonts, radius, spacing } from "@/src/theme";

type Props = {
  testID: string; label: string; icon?: LucideIconName; onPress: () => void; disabled?: boolean; loading?: boolean;
  bg: string; fg: string; border?: string; size?: "lg" | "md"; style?: StyleProp<ViewStyle>; textStyle?: StyleProp<TextStyle>;
};

const AP = Animated.createAnimatedComponent(Pressable);

export function PressButton({ testID, label, icon, onPress, disabled, loading, bg, fg, border, size = "lg", style, textStyle }: Props) {
  const s = useSharedValue(1);
  const a = useAnimatedStyle(() => ({ transform: [{ scale: s.value }] }));
  return (
    <AP
      testID={testID}
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={onPress}
      onPressIn={() => { s.value = withSpring(0.98); }}
      onPressOut={() => { s.value = withSpring(1); }}
      style={[styles.base, size === "lg" ? styles.lg : styles.md, { backgroundColor: bg, borderColor: border || bg, opacity: disabled ? 0.6 : 1 }, a, style]}
    >
      {loading ? <ActivityIndicator color={fg} /> : icon ? <Lucide name={icon} size={size === "lg" ? 24 : 20} color={fg} /> : null}
      <Text style={[size === "lg" ? styles.lgText : styles.mdText, { color: fg }, textStyle]}>{label}</Text>
    </AP>
  );
}

const styles = StyleSheet.create({
  base: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.md, borderRadius: radius.xl, borderWidth: 2 },
  lg: { minHeight: 64, paddingHorizontal: spacing.lg },
  md: { minHeight: 48, paddingHorizontal: spacing.lg, borderRadius: radius.lg },
  lgText: { fontFamily: fonts.bodySemi, fontSize: 19 },
  mdText: { fontFamily: fonts.bodySemi, fontSize: 16 },
});
