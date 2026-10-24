import AsyncStorage from "@react-native-async-storage/async-storage";

const storage = {
  getItem: (k: string) => AsyncStorage.getItem(k),
  setItem: (k: string, v: string) => AsyncStorage.setItem(k, v),
  removeItem: (k: string) => AsyncStorage.removeItem(k),
  async getJSON<T>(k: string): Promise<T | null> {
    const v = await AsyncStorage.getItem(k);
    try { return v ? (JSON.parse(v) as T) : null; } catch { return null; }
  },
  setJSON: (k: string, v: unknown) => AsyncStorage.setItem(k, JSON.stringify(v)),
};

export default storage;
