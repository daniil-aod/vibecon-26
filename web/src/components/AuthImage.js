import { useEffect, useState } from "react";
import { useApi } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

// Loads an authenticated file (BOL photo) as a blob URL, since <img> cannot send headers.
export const AuthImage = ({ fileId, alt, className, testid }) => {
  const api = useApi();
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let u;
    let off = false;
    api.get(`/files/${fileId}`, { responseType: "blob" })
      .then((r) => { if (!off) { u = URL.createObjectURL(r.data); setUrl(u); } })
      .catch(() => setErr(true));
    return () => { off = true; if (u) URL.revokeObjectURL(u); };
  }, [fileId, api]);
  if (err) return <div className={`grid place-items-center bg-muted text-xs text-muted-foreground ${className}`}>Photo unavailable</div>;
  if (!url) return <Skeleton className={className} />;
  return <img data-testid={testid} src={url} alt={alt} className={`object-cover ${className}`} />;
};
