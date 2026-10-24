import { Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";

export type UploadFile = { field: string; uri: string; filename: string; type: string };

/** Multipart upload that works on iOS, Android (expo/fetch) and web. */
export async function uploadForm(url: string, files: UploadFile[]) {
  const form = new FormData();
  for (const f of files) {
    if (Platform.OS === "web") {
      const blob = await (await fetch(f.uri)).blob();
      form.append(f.field, blob, f.filename);
    } else {
      const blob = await (await expoFetch(f.uri)).blob();
      form.append(f.field, blob as unknown as Blob, f.filename);
    }
  }
  if (Platform.OS === "web") return fetch(url, { method: "POST", body: form });
  return expoFetch(url, { method: "POST", body: form });
}
