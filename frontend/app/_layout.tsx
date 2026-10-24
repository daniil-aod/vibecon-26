import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { ToastProvider } from "@/src/components/Toast";
import { colors } from "@/src/theme";
// Registers the background location task at startup (must be imported at module scope).
import "@/src/lib/tracking";

export default function RootLayout() {
  // Prewarm the icon font together with the app fonts so icons never render blank on Expo Go Android.
  const [loaded, error] = useFonts({
    Lucide: require("@react-native-vector-icons/lucide/fonts/Lucide.ttf"),
    "SpaceGrotesk-600": require("../assets/fonts/SpaceGrotesk-600.ttf"),
    "SpaceGrotesk-700": require("../assets/fonts/SpaceGrotesk-700.ttf"),
    "IBMPlexSans-400": require("../assets/fonts/IBMPlexSans-400.ttf"),
    "IBMPlexSans-500": require("../assets/fonts/IBMPlexSans-500.ttf"),
    "IBMPlexSans-600": require("../assets/fonts/IBMPlexSans-600.ttf"),
    "IBMPlexMono-Regular": require("../assets/fonts/IBMPlexMono-Regular.ttf"),
    "IBMPlexMono-SemiBold": require("../assets/fonts/IBMPlexMono-SemiBold.ttf"),
  });

  if (!loaded && !error) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <KeyboardProvider>
          <ToastProvider>
            <StatusBar style="dark" />
            <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }} />
          </ToastProvider>
        </KeyboardProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
