import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, AppState, Linking, Modal, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Location from "expo-location";
import * as ImagePicker from "expo-image-picker";
import * as Haptics from "expo-haptics";
import Constants, { ExecutionEnvironment } from "expo-constants";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Animated, { FadeIn, FadeInDown } from "react-native-reanimated";
import Lucide from "@react-native-vector-icons/lucide";
import { Logo } from "@/src/components/Logo";
import { PressButton } from "@/src/components/PressButton";
import { FacilityMap } from "@/src/components/FacilityMap";
import { useToast } from "@/src/components/Toast";
import { ApiError, driverApi, DriverPayload, errMsg, Fix, recallApi, rememberApi, resolveApi, Stop } from "@/src/lib/api";
import { clearRide, getRide, getTrip, on, queuedCount, flushQueue, resumeTracking, Ride, startTracking, stopTracking, TrackingMode, tripComplete, watchZone } from "@/src/lib/tracking";
import { useI18n } from "@/src/lib/i18n";
import { LangToggle } from "@/src/components/LangToggle";
import { TripSummary } from "@/src/components/TripSummary";
import { backgroundState, ensureForeground, ensurePrecise, isPrecise, LocIssue, requestBackground } from "@/src/lib/permissions";
import { clock, dist, fmtClock, hrs } from "@/src/lib/format";
import { colors, fonts, radius, spacing } from "@/src/theme";

const isIOS = Platform.OS === "ios";
// Expo Go can't track in the background (its own permissions have no "Always"); a real build can.
const isExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

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
  const { t: L } = useI18n();
  const LRef = useRef(L);
  LRef.current = L;
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
  const [queued, setQueued] = useState(0);
  const [endSheet, setEndSheet] = useState(false);
  const [ride, setRide] = useState<Ride | null>(null);
  const zoneRef = useRef<Record<string, { a: boolean; d: boolean }> | null>(null);
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
    try { const p = await driverApi.get(api, token); setD(p); watchZone(p); setErr(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setErr("invalid"); const t = await getTrip(); if (t?.token === token) await stopTracking("invalid"); }
      else if (!d) setErr(errMsg(e));
    }
  }, [api, token, d]);

  useEffect(() => { load(); }, [api]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const i = setInterval(load, 20000); return () => clearInterval(i); }, [load]);

  // Re-attach tracking if this load was already started (app reopened / relaunched).
  useEffect(() => {
    (async () => {
      setRide(await getRide(token));
      const t = await getTrip();
      if (t?.token !== token) return;
      const fg = await Location.getForegroundPermissionsAsync().catch(() => null);
      if (!fg?.granted) { setIssue("blocked"); return; }
      setPreciseOff(!isPrecise(fg));
      setMode(await resumeTracking());
    })();
  }, [token]);

  // Subtle feedback when the geofence stamps a zone entry/exit (from any update: ping, refresh).
  useEffect(() => {
    if (!d) return;
    const snap: Record<string, { a: boolean; d: boolean }> = {};
    d.stops.forEach((s) => { snap[s.id] = { a: !!s.arrived_at, d: !!s.departed_at }; });
    const prev = zoneRef.current;
    zoneRef.current = snap;
    if (!prev) return;
    for (const s of d.stops) {
      const p = prev[s.id];
      if (!p) continue;
      if (!p.d && s.departed_at) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
        const m = s.arrived_at ? (new Date(s.departed_at).getTime() - new Date(s.arrived_at).getTime()) / 60000 : 0;
        toastRef.current.info(LRef.current.zoneLeft(s.facility_name, hrs(m)));
      } else if (!p.a && s.arrived_at) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
        toastRef.current.success(LRef.current.zoneEntered(s.facility_name));
      }
    }
  }, [d]);

  useEffect(() => {
    queuedCount().then(setQueued);
    flushQueue();
    const appSub = AppState.addEventListener("change", (s) => { if (s === "active") flushQueue(); });
    const retry = setInterval(() => { flushQueue(); }, 15000);
    const a = on("fix", (f) => setPos(f));
    const q = on("queue", (n) => setQueued(n));
    const b = on("payload", (p) => setD(p));
    const c = on("stopped", () => setMode(null));
    return () => { a(); b(); c(); q(); appSub.remove(); clearInterval(retry); };
  }, []);

  const begin = async () => {
    if (!api) return;
    setBgSheet(false);
    const m = await startTracking(token, api);
    setMode(m);
    setRide(await getRide(token));
    // Tell the backend the main trip timer started (web timeline shows it). Older backends without this route are fine.
    driverApi.rideStart(api, token).then((p) => setD(p)).catch(() => {});
    setBgDenied(m === "foreground" && Platform.OS !== "web");
    toast.success(m === "background" ? L.toastStartedBg : L.toastStartedFg);
  };

  const start = async () => {
    setBusy("start");
    try {
      const { issue: iss, perm } = await ensureForeground();
      setIssue(iss);
      if (iss || !perm) return;
      setPreciseOff(!(await ensurePrecise(perm)));
      const bg = await backgroundState();
      if (!bg.granted && bg.canAsk && Platform.OS !== "web" && !isExpoGo) { setBgSheet(true); return; }
      await begin();
    } catch (e) { toast.error(errMsg(e, L.startFail)); } finally { setBusy(""); }
  };

  const allowBackground = async () => {
    setBgSheet(false);
    const ok = await requestBackground();
    setBgDenied(!ok);
    await begin();
  };

  const upload = async (stop: Stop, asset: ImagePicker.ImagePickerAsset) => {
    if (!api) return;
    setBusy("bol");
    try {
      const data = await driverApi.bol(api, token, stop.id, asset.uri, asset.mimeType || "image/jpeg");
      setD(data);
      toast.success(L.toastBol);
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

  // Fail-safe: the driver can end recording manually (e.g. BOL can't be photographed).
  const endTrip = async () => {
    setEndSheet(false);
    await flushQueue();
    await stopTracking("ended");
    setRide(await getRide(token));
    // End the load's main timer on the backend too; this also closes any open zone (departure = now).
    if (api) {
      try { setD(await driverApi.rideEnd(api, token, pos)); } catch { /* older backend: local end only */ }
    }
    toast.info(L.toastEnded);
  };

  const resetTest = async () => {
    if (!api) return;
    setBusy("reset");
    try {
      if ((await getTrip())?.token === token) await stopTracking("reset");
      await clearRide(token);
      setRide(null);
      zoneRef.current = null;
      setD(await driverApi.resetTest(api, token));
      setPos(null);
      toast.success(L.resetDone);
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(""); }
  };

  const header = (
    <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
      <Pressable testID="driver-home-button" onPress={() => router.replace("/")} hitSlop={8}><Logo /></Pressable>
      <View style={styles.rowC}>
        {d && <Text style={styles.loadNo} testID="driver-load-number">{d.load_number}</Text>}
        <LangToggle />
      </View>
    </View>
  );

  if (err) return (
    <View style={styles.root}>{header}
      <View style={styles.center} testID="driver-link-error">
        <Lucide name="triangle-alert" size={40} color={colors.warning} />
        <Text style={styles.errT}>{err === "invalid" ? L.invalidLink : err}</Text>
        <Text style={styles.muted}>{L.askNewLink}</Text>
        <PressButton testID="driver-retry-button" size="md" label={L.tryAgain} icon="refresh-cw" onPress={load} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg }} />
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
  const away = cur && pos && cur.lat != null && cur.lng != null ? Math.max(0, dist(pos, { lat: cur.lat, lng: cur.lng }) - (cur.radius_m || 45)) : null;
  const tracking = !!mode;
  // Same ride times as the web app when the backend has them; local record otherwise.
  const srv = d.ride?.started_at ? { startedAt: d.ride.started_at, endedAt: d.ride.ended_at || undefined } : null;
  const shownRide: Ride | null = tracking ? (srv && !srv.endedAt ? srv : ride) : (srv?.endedAt ? srv : ride);
  const rideSecs = shownRide ? ((shownRide.endedAt ? new Date(shownRide.endedAt).getTime() : now) - new Date(shownRide.startedAt).getTime()) / 1000 : 0;
  const complete = tripComplete(d);

  const gpsTone = issue ? styles.chipWarn : !tracking ? styles.chipIdle : pos ? styles.chipOk : styles.chipIdle;
  const gpsText = issue === "blocked" ? L.gpsBlocked
    : issue === "services" ? L.gpsServices
    : !tracking ? (shownRide?.endedAt ? L.gpsFinished : L.gpsIdle)
    : pos ? `${L.gpsOn} · ±${Math.round(pos.accuracy)} m · ${preciseOff ? L.approximate : L.precise} · ${mode === "background" ? L.canLock : L.keepOpen}`
    : L.gpsFinding;
  const stopType = (s: string) => (s === "pickup" ? L.pickup : s === "delivery" ? L.delivery : s);

  return (
    <View style={styles.root}>
      {header}
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
        {issue && (
          <Animated.View entering={FadeIn} style={styles.px} testID="driver-location-blocked">
            <View style={styles.warnCard}>
              <View style={styles.rowC}><Lucide name="lock" size={20} color={colors.warningText} /><Text style={styles.warnH}>{issue === "services" ? L.turnOnServices : L.turnOnLocation}</Text></View>
              <Text style={styles.warnP}>{L.locWhy}</Text>
              <View style={{ gap: 4, marginTop: spacing.md }}>
                {(issue === "services"
                  ? isIOS ? L.stepsServicesIOS : L.stepsServicesAndroid
                  : isIOS ? L.stepsBlockedIOS : L.stepsBlockedAndroid
                ).map((s, i) => <Text key={s} style={styles.warnLi}>{i + 1}. {s}</Text>)}
              </View>
              <View style={[styles.row2, { marginTop: spacing.md }]}>
                <PressButton testID="driver-open-settings-button" size="md" label={L.openSettings} icon="settings" onPress={() => Linking.openSettings()} bg={colors.warningText} fg={colors.primaryForeground} style={{ flex: 1 }} />
                <PressButton testID="driver-enable-location-button" size="md" label={L.tryAgain} icon="locate-fixed" onPress={start} bg={colors.surface} fg={colors.warningText} border={colors.warningText} style={{ flex: 1 }} />
              </View>
              <Text style={styles.warnFoot}>{L.noGps}</Text>
            </View>
          </Animated.View>
        )}

        {!issue && preciseOff && tracking && (
          <View style={styles.px} testID="driver-precise-off">
            <View style={styles.warnCard}>
              <View style={styles.rowC}><Lucide name="crosshair" size={20} color={colors.warningText} /><Text style={styles.warnH}>{L.preciseTitle}</Text></View>
              <Text style={styles.warnP}>{L.preciseBody} {isIOS ? L.preciseIOS : L.preciseAndroid}</Text>
              <PressButton testID="driver-precise-settings-button" size="md" label={L.openSettings} icon="settings" onPress={() => Linking.openSettings()} bg={colors.warningText} fg={colors.primaryForeground} style={{ marginTop: spacing.md }} />
            </View>
          </View>
        )}

        {!issue && bgDenied && tracking && mode === "foreground" && (
          <View style={styles.px} testID="driver-background-limited">
            <View style={styles.infoCard}>
              {isExpoGo ? (
                <Text style={styles.infoT} testID="driver-expo-go-note">{L.expoGoNote}</Text>
              ) : (
                <>
                  <Text style={styles.infoT}>{L.bgLimited1}<Text style={styles.b}>{isIOS ? L.always : L.allTheTime}</Text>.</Text>
                  <Pressable testID="driver-background-settings-link" onPress={() => Linking.openSettings()} hitSlop={8}><Text style={styles.link}>{L.openSettings}</Text></Pressable>
                </>
              )}
            </View>
          </View>
        )}

        <View style={styles.px}>
          <Text style={styles.hi}>{L.hi} {d.driver_name || L.driver} · <Text style={styles.mutedInline}>{d.fleet_name}</Text></Text>
          <View style={[styles.chip, gpsTone]} testID="driver-gps-status">
            <Lucide name="satellite" size={16} color={issue ? colors.warningText : tracking && pos ? colors.successText : colors.slate700} />
            <Text style={[styles.chipT, { color: issue ? colors.warningText : tracking && pos ? colors.successText : colors.slate700 }]}>{gpsText}</Text>
          </View>
          {queued > 0 && (
            <View style={[styles.chip, styles.chipWarn]} testID="driver-offline-queue">
              <Lucide name="wifi-off" size={16} color={colors.warningText} />
              <Text style={[styles.chipT, { color: colors.warningText }]}>{L.offlineSaved(queued)}</Text>
            </View>
          )}
        </View>

        {d.test_load && (
          <View style={styles.px} testID="driver-test-load-card">
            <View style={styles.infoCard}>
              <Text style={styles.infoT}>{L.testLoadNote}</Text>
              <Pressable testID="driver-reset-test-button" disabled={!!busy} onPress={resetTest} style={styles.resetBtn}>
                <Text style={styles.link}>{busy === "reset" ? "…" : L.resetTest}</Text>
              </Pressable>
            </View>
          </View>
        )}

        {!tracking && !shownRide?.endedAt && (
          <Animated.View entering={FadeInDown.duration(350)} style={styles.px}>
            <View style={styles.startCard} testID="driver-start-card">
              <Text style={styles.startK}>{L.readyK}</Text>
              <Text style={styles.startH}>{L.readyH}</Text>
              <Text style={styles.startP}>{L.readyP}</Text>
              {Platform.OS !== "web" && <Text style={styles.startHint}>{isIOS ? L.readyHintIOS : L.readyHintAndroid}</Text>}
              <PressButton testID="driver-start-button" label={L.startTrip} icon="play" loading={busy === "start"} onPress={start} bg={colors.accent} fg={colors.primary} style={{ marginTop: spacing.lg }} />
            </View>
          </Animated.View>
        )}

        {shownRide && (
          <View style={styles.px}>
            <View style={styles.timer} testID="driver-ride-timer">
              <Text style={styles.timerSub}>{shownRide.endedAt ? L.rideEndedAt(fmtClock(shownRide.endedAt)) : L.rideSince(fmtClock(shownRide.startedAt))}</Text>
              <Text style={styles.timerNum} testID="driver-ride-time">{clock(rideSecs)}</Text>
              {onSite && cur && !shownRide.endedAt ? (
                <Animated.View entering={FadeIn} style={styles.zoneBox} testID="driver-zone-timer">
                  <Text style={styles.zoneK}>{L.inZoneFor} · {cur.facility_name}</Text>
                  <Text style={styles.zoneNum} testID="driver-zone-time">{clock(dwell)}</Text>
                  <Text style={[styles.zoneSub, { color: freeLeft > 0 ? colors.warningGlow : colors.successGlow }]}>{freeLeft > 0 ? `${L.freeLeft} ${clock(freeLeft)}` : L.detentionRunning}</Text>
                </Animated.View>
              ) : !shownRide.endedAt ? (
                <Text style={styles.zoneIdle} testID="driver-zone-idle">{cur ? L.zoneWaiting : L.allZonesDone}</Text>
              ) : null}
            </View>
            {shownRide.endedAt && cur && !tracking && (
              <Pressable testID="driver-restart-ride-button" onPress={start} style={styles.resetBtn}>
                <Text style={styles.link}>{L.restartRide}</Text>
              </Pressable>
            )}
          </View>
        )}

        {cur ? (
          <View style={styles.section}>
            <Text style={styles.kicker}>{onSite ? L.atDock : L.headingTo} · {stopType(cur.type)}</Text>
            <Text style={styles.facility} testID="driver-facility-name">{cur.facility_name}</Text>
            {!!cur.address && <View style={styles.addrRow}><Lucide name="map-pin" size={16} color={colors.slate700} style={{ marginTop: 3 }} /><Text style={styles.addr}>{cur.address}</Text></View>}
            {!onSite && away !== null && (
              <View style={styles.awayRow} testID="driver-distance"><Lucide name="navigation" size={16} color={colors.slate700} /><Text style={styles.addr}>{away < 50 ? L.atGate : L.miAway((away / 1609).toFixed(1))}</Text></View>
            )}
            <View style={{ marginTop: spacing.lg }}><FacilityMap testID="driver-map" stop={cur} truck={pos} height={200} /></View>
            <Text style={styles.hint}>{L.autoHint}</Text>
          </View>
        ) : (
          <View style={styles.section} testID="driver-all-done">
            <View style={{ alignItems: "center" }}>
              <Lucide name="circle-check" size={48} color={colors.successStrong} />
              <Text style={[styles.facility, { marginTop: spacing.md }]}>{L.allDone}</Text>
              <Text style={styles.muted} testID="driver-all-done-note">{!tracking ? (d.documents_needed?.length ? L.docsStillNeeded : L.allDoneP) : complete ? L.tapEndRide : L.bolToFinish}</Text>
            </View>
            <TripSummary stops={stops} />
          </View>
        )}

        {bolStop?.arrived_at && (
          <View style={styles.section}>
            <PressButton
              testID="driver-upload-bol-button"
              label={bolStop.bol_count ? L.bolAttached(bolStop.bol_count) : L.bolPhoto}
              icon={bolStop.bol_count ? "circle-check" : "camera"}
              loading={busy === "bol"}
              onPress={() => (Platform.OS === "web" ? pickPhoto(bolStop) : setPhotoSheet("choose"))}
              bg={bolStop.bol_count ? colors.successSoft : colors.surface}
              fg={bolStop.bol_count ? colors.success : colors.slate900}
              border={bolStop.bol_count ? colors.successStrong : colors.slate900}
              textStyle={{ fontSize: 17 }}
            />
            <Text style={styles.hint}>{L.bolHint(bolStop.facility_name)}</Text>
          </View>
        )}

        {tracking && (
          <View style={styles.section}>
            <PressButton testID="driver-end-trip-button" label={L.endRide} icon="square" onPress={() => setEndSheet(true)}
              bg={complete ? colors.primary : colors.surface} fg={complete ? colors.primaryForeground : colors.slate900} border={colors.slate900} />
          </View>
        )}

        <View style={styles.section}>
          <Text style={styles.kicker}>{L.allStops}</Text>
          <View style={{ gap: spacing.sm, marginTop: spacing.sm }}>
            {stops.map((s, i) => (
              <View key={s.id} style={styles.stopRow} testID={`driver-stop-${i}`}>
                <View style={[styles.stopNum, s.departed_at ? { backgroundColor: colors.successStrong } : s.arrived_at ? { backgroundColor: colors.info } : null]}>
                  <Text style={[styles.stopNumT, (s.departed_at || s.arrived_at) && { color: colors.primaryForeground }]}>{i + 1}</Text>
                </View>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.stopName} numberOfLines={1}>{s.facility_name}</Text>
                  <Text style={styles.stopMeta}>
                    {s.departed_at && s.arrived_at ? `${L.inAt} ${fmtClock(s.arrived_at)} · ${L.outAt} ${fmtClock(s.departed_at)} · ${hrs((new Date(s.departed_at).getTime() - new Date(s.arrived_at).getTime()) / 60000)}` : s.arrived_at ? `${L.inAt} ${fmtClock(s.arrived_at)}` : stopType(s.type)}
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
            <Text style={styles.sheetH}>{L.bgSheetH}</Text>
            <Text style={styles.sheetP}>{L.bgSheetP1}<Text style={styles.b}>{isIOS ? L.bgSheetIOS : L.bgSheetAndroid}</Text>{L.bgSheetP2}</Text>
            <PressButton testID="driver-background-continue-button" label={L.continue} icon="check" onPress={allowBackground} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
            <Pressable testID="driver-background-skip-button" onPress={begin} style={styles.skip}><Text style={styles.skipT}>{L.notNow}</Text></Pressable>
          </View>
        </View>
      </Modal>

      <Modal visible={endSheet} transparent animationType="slide" onRequestClose={() => setEndSheet(false)}>
        <Pressable style={styles.overlay} onPress={() => setEndSheet(false)}>
          <Pressable style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]} testID="driver-end-trip-sheet">
            <View style={styles.grab} />
            <Lucide name="triangle-alert" size={28} color={colors.warning} />
            <Text style={styles.sheetH}>{L.endTripH}</Text>
            <Text style={styles.sheetP}>{L.endTripP}</Text>
            <PressButton testID="driver-end-trip-confirm-button" size="md" label={L.endTripConfirm} icon="square" onPress={endTrip} bg={colors.warningText} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
            <PressButton testID="driver-end-trip-cancel-button" size="md" label={L.keepTracking} onPress={() => setEndSheet(false)} bg={colors.surface} fg={colors.slate900} border={colors.slate900} style={{ marginTop: spacing.md, alignSelf: "stretch" }} />
          </Pressable>
        </Pressable>
      </Modal>

      <Modal visible={!!photoSheet} transparent animationType="slide" onRequestClose={() => setPhotoSheet(null)}>
        <Pressable style={styles.overlay} onPress={() => setPhotoSheet(null)}>
          <Pressable style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]} testID="driver-photo-sheet">
            <View style={styles.grab} />
            {photoSheet === "camera-blocked" ? (
              <>
                <Lucide name="camera-off" size={28} color={colors.warning} />
                <Text style={styles.sheetH}>{L.cameraOffH}</Text>
                <Text style={styles.sheetP}>{L.cameraOffP}</Text>
                <PressButton testID="driver-camera-settings-button" size="md" label={L.openSettings} icon="settings" onPress={() => { setPhotoSheet(null); Linking.openSettings(); }} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
              </>
            ) : (
              <>
                <Text style={styles.sheetH}>{L.attachBolH}</Text>
                <Text style={styles.sheetP}>{L.attachBolP}</Text>
                <PressButton testID="driver-take-photo-button" size="md" label={L.takePhoto} icon="camera" onPress={() => bolStop && takePhoto(bolStop)} bg={colors.primary} fg={colors.primaryForeground} style={{ marginTop: spacing.lg, alignSelf: "stretch" }} />
              </>
            )}
            <PressButton testID="driver-choose-photo-button" size="md" label={L.choosePhoto} icon="image" onPress={() => bolStop && pickPhoto(bolStop)} bg={colors.surface} fg={colors.slate900} border={colors.slate900} style={{ marginTop: spacing.md, alignSelf: "stretch" }} />
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
  resetBtn: { minHeight: 44, justifyContent: "center", alignSelf: "flex-start" },
  endBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, minHeight: 48, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border },
  endT: { fontFamily: fonts.bodyMedium, fontSize: 15, color: colors.mutedForeground },
  zoneBox: { marginTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.slate700, paddingTop: spacing.md },
  zoneK: { fontFamily: fonts.bodySemi, fontSize: 12, letterSpacing: 1, textTransform: "uppercase", color: colors.accentSoft },
  zoneNum: { fontFamily: fonts.monoSemi, fontSize: 32, color: colors.primaryForeground, marginTop: spacing.xs, fontVariant: ["tabular-nums"] },
  zoneSub: { fontFamily: fonts.bodyMedium, fontSize: 14, marginTop: spacing.xs },
  zoneIdle: { fontFamily: fonts.body, fontSize: 14, color: colors.slate400, marginTop: spacing.md },
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
