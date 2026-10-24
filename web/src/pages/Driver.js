import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";

// Driver tracking moved to the DockClock Driver mobile app. Old /d/:token links forward to the
// backend landing page, which opens the app (or explains how to install it).
export default function Driver() {
  const { token } = useParams();
  useEffect(() => {
    window.location.replace(`/api/open/${encodeURIComponent(token)}`);
  }, [token]);
  return (
    <div data-testid="driver-page" className="grid min-h-screen place-items-center">
      <Loader2 className="h-8 w-8 animate-spin" />
    </div>
  );
}
