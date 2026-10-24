const ls = () => (typeof window !== "undefined" ? window.localStorage : null);

const storage = {
  getItem: async (k: string) => ls()?.getItem(k) ?? null,
  setItem: async (k: string, v: string) => { ls()?.setItem(k, v); },
  removeItem: async (k: string) => { ls()?.removeItem(k); },
  async getJSON<T>(k: string): Promise<T | null> {
    const v = ls()?.getItem(k);
    try { return v ? (JSON.parse(v) as T) : null; } catch { return null; }
  },
  setJSON: async (k: string, v: unknown) => { ls()?.setItem(k, JSON.stringify(v)); },
};

export default storage;
