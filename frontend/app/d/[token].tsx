import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Linking, Modal, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Location from "expo-location";
import * as ImagePicker from "expo-image-picker";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Animated, { FadeIn, FadeInDown } from "react-native-reanimated";
import Lucide from "@react-native-vector-icons/lucide";
import { Logo } from "@/src/components/Logo";
import { PressButton } from "@/src/components/PressButton";
import { FacilityMap } from "@/src/components/FacilityMap";
import { useToast } from "@/src/components/Toast";
import { ApiError, driverApi, DriverPayload, errMsg, Fix, recallApi, rememberApi, resolveApi, Stop } from "@/src/lib/api";
import { getTrip, on, resumeTracking, startTracking, stopTracking, TrackingMode } from "@/src/lib/tracking";
import { backgroundState, ensureForeground, ensurePrecise, isPrecise, LocIssue, requestBackground } from "@/src/lib/permissions";
import { clock, dist, fmtClock, hrs } from "@/src/lib/format";
import { colors, fonts, radius, spacing } from "@/src/theme";

const isIOS = Platform.OS === "ios";

function useNow(ms = 1000) {
  const [n, setN] = useState(Date.now());
  useEffect(() => { const i = setInterval(() => setN(Date.now()), ms); return () => clearInterval(i); }, [ms]);
  return n;
}

export default function DriverScreen() {
  const { token, api: apiParam } = useLocalSearchParams<{ token: string; api?: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const now = useNow(1000);

  const [api, setApi] = useState<string | null>(null);
  const [d, setD] = useState<DriverPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pos, setPos] = useState<Fix | null>(null);
  const [mode, setMode] = useState<TrackingMode | null>(null);
  const [issue, setIssue] = useState<LocIssue>(null);
  const [preciseOff, setPreciseOff] = useState(false);
  const [bgSheet, setBgSheet] = useState(false);
  const [bgDenied, setBgDenied] = useState(false);
  const [photoSheet, setPhotoSheet] = useState<null | "choose" | "camera-blocked">(null);
  const [busy, setBusy] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const toastRef = useRef(toast);
  toastRef.current = toast;

  // Resolve which DockClock backend this load lives on (from the texted link) and remember it.
  useEffect(() => {
    (async () => {
      const a = apiParam ? resolveApi(apiParam) : await recallApi(token);
      await rememberApi(token, a);
      setApi(a);
    })();
  }, [token, apiParam]);

  const load = useCallback(async () => {
    if (!api) return;
    try { setD(await driverApi.get(api, token)); setErr(null); } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setErr("This link is not valid"); const t = await getTrip(); if (t?.token === token) await stopTracking("invalid"); }
      else if (!d) setErr(errMsg(e));
    }
  }, [api, token, d]);

  useEffect(() => { load(); }, [api]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const i = setInterval(load, 20000); return () => clearInterval(i); }, [load]);

  // Re-attach tracking if this load was already started (app reopened / relaunched).
  useEffect(() => {
    (async () => {
      const t = await getTrip();
      if (t?.token !== token) return;
      const fg = await Location.getForegroundPermissionsAsync().catch(() => null);
      if (!fg?.granted) { setIssue("blocked"); return; }
      setPreciseOff(!isPrecise(fg));
      setMode(await resumeTracking());
    })();
  }, [token]);

  useEffect(() => {
    const a = on("fix", (f) => setPos(f));
    const b = on("payload", (p) => {
      setD(p);
      if (p.event === "arrived") toastRef.current.success("Arrival stamped by geofence. Free time is running.");
      if (p.event === "departed") toastRef.current.success("Departure stamped. Don't forget the BOL photo.");
    });
    const c = on("stopped", ({ reason }) => {
      setMode(null);
      if (reason === "delivered") toastRef.current.success("Load delivered — tracking stopped.");
    });
    return () => { a(); b(); c(); };
  }, []);

  const begin = async () => {
    if (!api) return;
    setBgSheet(false);
    const m = await startTracking(token, api);
    setMode(m);
    setBgDenied(m === "foreground" && Platform.OS !== "web");
    toast.success(m === "background" ? "Tracking started — you can lock your phone." : "Tracking started — keep DockClock open.");
  };

  const start = async () => {
    setBusy("start");
    try {
      const { issue: iss, perm } = await ensureForeground();
      setIssue(iss);
      if (iss || !perm) return;
      setPreciseOff(!(await ensurePrecise(perm)));
      const bg = await backgroundState();
      if (!bg.granted && bg.canAsk && Platform.OS !== "web") { setBgSheet(true); return; }
      await begin();
    } catch (e) { toast.error(errMsg(e, "Couldn't start location")); } finally { setBusy(""); }
  };

  const allowBackground = async () => {
    setBgSheet(false);
    const ok = await requestBackground();
    setBgDenied(!ok);
    await begin();
  };

  const getFix = async (): Promise<Fix> => {
    if (pos && pos.accuracy < 1000) return pos;
    const { issue: iss } = await ensureForeground();
    if (iss) { setIssue(iss); throw new Error("Turn on location so your tap is stamped with GPS"); }
    const l = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Highest });
    const f = { lat: l.coords.latitude, lng: l.coords.longitude, accuracy: l.coords.accuracy ?? 50 };
    setPos(f);
    return f;
  };

  const tap = async (stop: Stop, action: "arrive" | "depart") => {
    if (!api) return;
    setBusy(action);
    try {
      const fix = await getFix();
      const data = await driverApi.tap(api, token, stop.id, action, fix);
      setD(data);
      toast.success(action === "arrive" ? "Arrival stamped with GPS" : "Departure stamped with GPS");
      if (data.stops.every((s) => s.departed_at) && (await getTrip())?.token === token) await stopTracking("delivered");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };

  const upload = async (stop: Stop, asset: ImagePicker.ImagePickerAsset) => {
    if (!api) return;
    setBusy("bol");
    try {
      setD(await driverApi.bol(api, token, stop.id, asset.uri, asset.mimeType || "image/jpeg"));
      toast.success("BOL photo attached to the load");
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };

  const takePhoto = async (stop: Stop) => {
    setPhotoSheet(null);
    let p = await ImagePicker.getCameraPermissionsAsync();
    if (!p.granted && p.canAskAgain) p = await ImagePicker.requestCameraPermissionsAsync();
    if (!p.granted) { setPhotoSheet("camera-blocked"); return; }
    const r = await ImagePicker.launchCameraAsync({ quality: 0.7, mediaTypes: ["images"] });
    if (!r.canceled && r.assets?.[0]) await upload(stop, r.assets[0]);
  };

  const pickPhoto = async (stop: Stop) => {
    setPhotoSheet(null);
    const r = await ImagePicker.launchImageLibraryAsync({ quality: 0.7, mediaTypes: ["images"] });
    if (!r.canceled && r.assets?.[0]) await upload(stop, r.assets[0]);
  };

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const header = (
    <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
      <Pressable testID="driver-home-button" onPress={() => router.replace("/")} hitSlop={8}><Logo /></Pressable>
      {d && <Text style={styles.loadNo} testID="driver-load-number">{d.load_number}</Text>}
    </View>
  );

  if (err) return (
    <View style={styles.root}>{header}
      <View style={styles.center} testID="driver-link-error">
        <Lucide name="triangle-alert" size={40} color={colors.warning} />
        <Text style={styles.errT}>{err}</Text>
        <Text style={styles.muted}>Ask your dispatcher to text you a new link.</Text>
        <PressButton testID="driver-retry-button" size="md" label="Try again" icon="refresh-cw" onPress={load} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg }} />
      </View>
    </View>
  );
  if (!d) return <View style={styles.root}>{header}<View style={styles.center}><ActivityIndicator size="large" color={colors.slate900} /></View></View>;

  const stops = [...d.stops].sort((a, b) => a.seq - b.seq);
  const cur = stops.find((s) => !s.departed_at);
  const lastDone = [...stops].reverse().find((s) => s.departed_at);
  const bolStop = cur?.arrived_at ? cur : lastDone || cur;
  const onSite = !!(cur?.arrived_at && !cur?.departed_at);
  const dwell = onSite && cur?.arrived_at ? (now - new Date(cur.arrived_at).getTime()) / 1000 : 0;
  const freeLeft = onSite && cur?.free_expires_at ? (new Date(cur.free_expires_at).getTime() - now) / 1000 : 0;
  const away = cur && pos && cur.lat != null && cur.lng != null ? Math.max(0, dist(pos, { lat: cur.lat, lng: cur.lng }) - (cur.radius_m || 300)) : null;
  const tracking = !!mode;

  const gpsTone = issue ? styles.chipWarn : !tracking ? styles.chipIdle : pos ? styles.chipOk : styles.chipIdle;
  const gpsText = issue === "blocked" ? "Location is off — turn it on above"
    : issue === "services" ? "Location Services are off — turn them on above"
    : !tracking ? (cur ? "Tap Start trip to share your location" : "Tracking finished")
    : pos ? `GPS on · ±${Math.round(pos.accuracy)} m${preciseOff ? " · approximate" : " · precise"} · ${mode === "background" ? "you can lock your phone" : "keep the app open"}`
    : "Finding your location…";

  return (
    <View style={styles.root}>
      {header}
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
        {issue && (
          <Animated.View entering={FadeIn} style={styles.px} testID="driver-location-blocked">
            <View style={styles.warnCard}>
              <View style={styles.rowC}><Lucide name="lock" size={20} color={colors.warningText} /><Text style={styles.warnH}>{issue === "services" ? "Turn on Location Services" : "Turn on location"}</Text></View>
              <Text style={styles.warnP}>DockClock needs your location to auto-stamp your in and out times at the dock. It's only used while this load is open.</Text>
              <View style={{ gap: 4, marginTop: spacing.md }}>
                {(issue === "services"
                  ? isIOS ? ["Open Settings › Privacy & Security", "Turn on Location Services"] : ["Swipe down from the top of the screen", "Tap Location to turn it on"]
                  : isIOS ? ["Tap Open Settings below", "Location → choose While Using the App (or Always)", "Turn on Precise Location"] : ["Tap Open Settings below", "Permissions → Location → Allow all the time", "Turn on Use precise location"]
                ).map((s, i) => <Text key={s} style={styles.warnLi}>{i + 1}. {s}</Text>)}
              </View>
              <View style={[styles.row2, { marginTop: spacing.md }]}>
                <PressButton testID="driver-open-settings-button" size="md" label="Open Settings" icon="settings" onPress={() => Linking.openSettings()} bg={colors.warningText} fg={colors.primaryForeground} style={{ flex: 1 }} />
                <PressButton testID="driver-enable-location-button" size="md" label="Try again" icon="locate-fixed" onPress={start} bg={colors.surface} fg={colors.warningText} border={colors.warningText} style={{ flex: 1 }} />
              </View>
              <Text style={styles.warnFoot}>No GPS? You can still tap “I'm at the dock” below and your dispatcher will confirm the time.</Text>
            </View>
          </Animated.View>
        )}

        {!issue && preciseOff && tracking && (
          <View style={styles.px} testID="driver-precise-off">
            <View style={styles.warnCard}>
              <View style={styles.rowC}><Lucide name="crosshair" size={20} color={colors.warningText} /><Text style={styles.warnH}>Turn on Precise Location</Text></View>
              <Text style={styles.warnP}>Your phone is sharing an approximate location, so the dock can't stamp exact times. {isIOS ? "In Settings › DockClock Driver › Location, switch on Precise Location." : "In Settings › Location, switch on Use precise location."}</Text>
              <PressButton testID="driver-precise-settings-button" size="md" label="Open Settings" icon="settings" onPress={() => Linking.openSettings()} bg={colors.warningText} fg={colors.primaryForeground} style={{ marginTop: spacing.md }} />
            </View>
          </View>
        )}

        {!issue && bgDenied && tracking && mode === "foreground" && (
          <View style={styles.px} testID="driver-background-limited">
            <View style={styles.infoCard}>
              <Text style={styles.infoT}>Tracking pauses if DockClock is closed. To keep stamping with your phone locked, allow location <Text style={styles.b}>{isIOS ? "Always" : "All the time"}</Text>.</Text>
              <Pressable testID="driver-background-settings-link" onPress={() => Linking.openSettings()} hitSlop={8}><Text style={styles.link}>Open Settings</Text></Pressable>
            </View>
          </View>
        )}

        <View style={styles.px}>
          <Text style={styles.hi}>Hi {d.driver_name || "driver"} · <Text style={styles.mutedInline}>{d.fleet_name}</Text></Text>
          <View style={[styles.chip, gpsTone]} testID="driver-gps-status">
            <Lucide name="satellite" size={16} color={issue ? colors.warningText : tracking && pos ? colors.successText : colors.slate700} />
            <Text style={[styles.chipT, { color: issue ? colors.warningText : tracking && pos ? colors.successText : colors.slate700 }]}>{gpsText}</Text>
          </View>
        </View>

        {cur && !tracking && (
          <Animated.View entering={FadeInDown.duration(350)} style={styles.px}>
            <View style={styles.startCard} testID="driver-start-card">
              <Text style={styles.startK}>Ready to roll</Text>
              <Text style={styles.startH}>Press Start once. That's it.</Text>
              <Text style={styles.startP}>DockClock stamps your arrival and departure at every stop automatically, even with your phone locked, until the load is delivered.</Text>
              {Platform.OS !== "web" && <Text style={styles.startHint}>When asked, allow location {isIOS ? "and keep Precise on" : "and choose Precise"}.</Text>}
              <PressButton testID="driver-start-button" label="Start trip" icon="play" loading={busy === "start"} onPress={start} bg={colors.accent} fg={colors.primary} style={{ marginTop: spacing.lg }} />
            </View>
          </Animated.View>
        )}

        {cur ? (
          <View style={styles.section}>
            <Text style={styles.kicker}>{onSite ? "At the dock" : "Heading to"} · {cur.type}</Text>
            <Text style={styles.facility} testID="driver-facility-name">{cur.facility_name}</Text>
            {!!cur.address && <View style={styles.addrRow}><Lucide name="map-pin" size={16} color={colors.slate700} style={{ marginTop: 3 }} /><Text style={styles.addr}>{cur.address}</Text></View>}
            {onSite ? (
              <View style={styles.timer} testID="driver-on-site-timer">
                <Text style={styles.timerSub}>On site since {fmtClock(cur.arrived_at)}</Text>
                <Text style={styles.timerNum}>{clock(dwell)}</Text>
                <Text style={[styles.timerState, { color: freeLeft > 0 ? colors.warningGlow : colors.successGlow }]}>{freeLeft > 0 ? `Free time left ${clock(freeLeft)}` : "Detention is running — broker notified"}</Text>
              </View>
            ) : away !== null && (
              <View style={styles.awayRow} testID="driver-distance"><Lucide name="navigation" size={16} color={colors.slate700} /><Text style={styles.addr}>{away < 50 ? "You're at the gate" : `${(away / 1609).toFixed(1)} mi from the geofence`}</Text></View>
            )}
            <View style={{ marginTop: spacing.lg }}><FacilityMap testID="driver-map" stop={cur} truck={pos} height={200} /></View>
            <View style={{ marginTop: spacing.xl, gap: spacing.md }}>
              {!cur.arrived_at && <PressButton testID="driver-arrived-button" label="I'm at the dock" icon="log-in" loading={busy === "arrive"} disabled={!!busy} onPress={() => tap(cur, "arrive")} bg={colors.primary} fg={colors.primaryForeground} />}
              {onSite && <PressButton testID="driver-departed-button" label="I'm leaving" icon="log-out" loading={busy === "depart"} disabled={!!busy} onPress={() => tap(cur, "depart")} bg={colors.success} fg={colors.primaryForeground} />}
              {!cur.arrived_at && <Text style={styles.hint}>Arrival is stamped automatically when you enter the facility. Tap only if it doesn't.</Text>}
            </View>
          </View>
        ) : (
          <View style={[styles.section, { alignItems: "center" }]} testID="driver-all-done">
            <Lucide name="circle-check" size={48} color={colors.successStrong} />
            <Text style={[styles.facility, { marginTop: spacing.md }]}>All stops done</Text>
            <Text style={styles.muted}>Thanks! Your times are saved and tracking has stopped.</Text>
          </View>
        )}

        {bolStop?.arrived_at && (
          <View style={styles.section}>
            <PressButton
              testID="driver-upload-bol-button"
              label={bolStop.bol_count ? `BOL attached (${bolStop.bol_count}) · add another` : "Photo of signed BOL"}
              icon={bolStop.bol_count ? "circle-check" : "camera"}
              loading={busy === "bol"}
              onPress={() => (Platform.OS === "web" ? pickPhoto(bolStop) : setPhotoSheet("choose"))}
              bg={bolStop.bol_count ? colors.successSoft : colors.surface}
              fg={bolStop.bol_count ? colors.success : colors.slate900}
              border={bolStop.bol_count ? colors.successStrong : colors.slate900}
              textStyle={{ fontSize: 17 }}
            />
            <Text style={styles.hint}>For {bolStop.facility_name}. Make sure the in and out times are readable.</Text>
          </View>
        )}

        <View style={styles.section}>
          <Text style={styles.kicker}>All stops</Text>
          <View style={{ gap: spacing.sm, marginTop: spacing.sm }}>
            {stops.map((s, i) => (
              <View key={s.id} style={styles.stopRow} testID={`driver-stop-${i}`}>
                <View style={[styles.stopNum, s.departed_at ? { backgroundColor: colors.successStrong } : s.arrived_at ? { backgroundColor: colors.info } : null]}>
                  <Text style={[styles.stopNumT, (s.departed_at || s.arrived_at) && { color: colors.primaryForeground }]}>{i + 1}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.stopName} numberOfLines={1}>{s.facility_name}</Text>
                  <Text style={styles.stopMeta}>
                    {s.departed_at && s.arrived_at ? `In ${fmtClock(s.arrived_at)} · Out ${fmtClock(s.departed_at)} · ${hrs((new Date(s.departed_at).getTime() - new Date(s.arrived_at).getTime()) / 60000)}` : s.arrived_at ? `In ${fmtClock(s.arrived_at)}` : s.type}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        </View>
      </ScrollView>

      {/* Pre-permission explanation before the OS "Always" prompt */}
      <Modal visible={bgSheet} transparent animationType="slide" onRequestClose={() => setBgSheet(false)}>
        <View style={styles.overlay}>
          <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]} testID="driver-background-sheet">
            <View style={styles.grab} />
            <Lucide name="lock" size={28} color={colors.accent} />
            <Text style={styles.sheetH}>Keep tracking with your phone locked</Text>
            <Text style={styles.sheetP}>So you don't have to keep DockClock open, allow location {isIOS ? <Text style={styles.b}>“Change to Always Allow”</Text> : <Text style={styles.b}>“Allow all the time”</Text>} on the next screen. It turns off automatically after delivery.</Text>
            <PressButton testID="driver-background-continue-button" label="Continue" icon="check" onPress={allowBackground} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
            <Pressable testID="driver-background-skip-button" onPress={begin} style={styles.skip}><Text style={styles.skipT}>Not now — I'll keep the app open</Text></Pressable>
          </View>
        </View>
      </Modal>

      <Modal visible={!!photoSheet} transparent animationType="slide" onRequestClose={() => setPhotoSheet(null)}>
        <Pressable style={styles.overlay} onPress={() => setPhotoSheet(null)}>
          <Pressable style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]} testID="driver-photo-sheet">
            <View style={styles.grab} />
            {photoSheet === "camera-blocked" ? (
              <>
                <Lucide name="camera-off" size={28} color={colors.warning} />
                <Text style={styles.sheetH}>Camera is off for DockClock</Text>
                <Text style={styles.sheetP}>Allow camera access in Settings to photograph the BOL, or choose a photo you already took.</Text>
                <PressButton testID="driver-camera-settings-button" size="md" label="Open Settings" icon="settings" onPress={() => { setPhotoSheet(null); Linking.openSettings(); }} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
              </>
            ) : (
              <>
                <Text style={styles.sheetH}>Attach the signed BOL</Text>
                <Text style={styles.sheetP}>Make sure the in and out times are readable.</Text>
                <PressButton testID="driver-take-photo-button" size="md" label="Take photo" icon="camera" onPress={() => bolStop && takePhoto(bolStop)} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
              </>
            )}
            <PressButton testID="driver-choose-photo-button" size="md" label="Choose from photos" icon="image" onPress={() => bolStop && pickPhoto(bolStop)} bg={colors.surface} fg={colors.slate900} border={colors.slate900} style={{ marginTop: spacing.md, alignSelf: "stretch" }} />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  loadNo: { fontFamily: fonts.monoSemi, fontSize: 14, color: colors.slate900 },
  errT: { fontFamily: fonts.bodySemi, fontSize: 18, color: colors.slate900, marginTop: spacing.md, textAlign: "center" },
  muted: { fontFamily: fonts.body, fontSize: 15, color: colors.mutedForeground, textAlign: "center" },
  px: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
  rowC: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  row2: { flexDirection: "row", gap: spacing.md },
  warnCard: { borderWidth: 2, borderColor: colors.warningBorder, backgroundColor: colors.warningSoft, borderRadius: radius.xl, padding: spacing.lg },
  warnH: { fontFamily: fonts.display, fontSize: 18, color: colors.warningText },
  warnP: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, color: colors.warningText, marginTop: spacing.xs },
  warnLi: { fontFamily: fonts.bodyMedium, fontSize: 14, color: colors.warningText },
  warnFoot: { fontFamily: fonts.body, fontSize: 12, color: colors.warningText, textAlign: "center", marginTop: spacing.sm, opacity: 0.85 },
  infoCard: { backgroundColor: colors.slate100, borderRadius: radius.lg, padding: spacing.md, gap: spacing.xs },
  infoT: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, color: colors.slate700 },
  link: { fontFamily: fonts.bodySemi, fontSize: 14, color: colors.accent, paddingVertical: spacing.xs },
  b: { fontFamily: fonts.bodySemi },
  hi: { fontFamily: fonts.body, fontSize: 16, color: colors.slate900 },
  mutedInline: { color: colors.mutedForeground },
  chip: { flexDirection: "row", alignItems: "center", gap: spacing.sm, borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, marginTop: spacing.md },
  chipT: { fontFamily: fonts.body, fontSize: 14, flex: 1 },
  chipWarn: { backgroundColor: colors.warningMid },
  chipIdle: { backgroundColor: colors.slate100 },
  chipOk: { backgroundColor: colors.successSoft },
  startCard: { backgroundColor: colors.primary, borderRadius: radius.xxl, padding: spacing.xl },
  startK: { fontFamily: fonts.bodySemi, fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: colors.accentSoft },
  startH: { fontFamily: fonts.display, fontSize: 24, color: colors.primaryForeground, marginTop: spacing.xs, letterSpacing: -0.3 },
  startP: { fontFamily: fonts.body, fontSize: 15, lineHeight: 22, color: colors.slate400, marginTop: spacing.sm },
  startHint: { fontFamily: fonts.bodyMedium, fontSize: 14, color: colors.primaryForeground, marginTop: spacing.md },
  section: { paddingHorizontal: spacing.lg, paddingTop: spacing.xl },
  kicker: { fontFamily: fonts.bodySemi, fontSize: 12, letterSpacing: 1.2, textTransform: "uppercase", color: colors.mutedForeground },
  facility: { fontFamily: fonts.display, fontSize: 24, lineHeight: 30, color: colors.slate900, marginTop: spacing.xs, letterSpacing: -0.3 },
  addrRow: { flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs },
  addr: { fontFamily: fonts.body, fontSize: 16, color: colors.slate700, flex: 1 },
  awayRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.md },
  timer: { backgroundColor: colors.primary, borderRadius: radius.xl, padding: spacing.xl, marginTop: spacing.lg },
  timerSub: { fontFamily: fonts.body, fontSize: 14, color: colors.slate400 },
  timerNum: { fontFamily: fonts.monoSemi, fontSize: 46, color: colors.primaryForeground, marginTop: spacing.xs, fontVariant: ["tabular-nums"] },
  timerState: { fontFamily: fonts.bodyMedium, fontSize: 16, marginTop: spacing.sm },
  hint: { fontFamily: fonts.body, fontSize: 14, color: colors.mutedForeground, textAlign: "center", marginTop: spacing.sm },
  stopRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.md },
  stopNum: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.slate100, alignItems: "center", justifyContent: "center" },
  stopNumT: { fontFamily: fonts.monoSemi, fontSize: 14, color: colors.slate900 },
  stopName: { fontFamily: fonts.bodyMedium, fontSize: 16, color: colors.slate900 },
  stopMeta: { fontFamily: fonts.body, fontSize: 14, color: colors.mutedForeground, textTransform: "none" },
  overlay: { flex: 1, backgroundColor: colors.overlay, justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: radius.xxl, borderTopRightRadius: radius.xxl, padding: spacing.xl, alignItems: "flex-start" },
  grab: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: spacing.lg },
  sheetH: { fontFamily: fonts.display, fontSize: 22, color: colors.slate900, marginTop: spacing.sm },
  sheetP: { fontFamily: fonts.body, fontSize: 15, lineHeight: 22, color: colors.slate700, marginTop: spacing.sm },
  skip: { alignSelf: "center", paddingVertical: spacing.md, marginTop: spacing.sm },
  skipT: { fontFamily: fonts.bodyMedium, fontSize: 15, color: colors.mutedForeground },
});
