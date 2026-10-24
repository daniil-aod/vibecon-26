{
  "brand": {
    "name": "DockClock",
    "tagline": "Collect the detention you already earned.",
    "personality": [
      "calm control room (dispatcher)",
      "sunlight-readable utility (driver)",
      "legal-exhibit neutrality (broker evidence)",
      "high-trust, money-forward"
    ],
    "north_star": "Map-first operations + finance: every minute becomes evidence, every evidence becomes invoice."
  },

  "design_tokens": {
    "fonts_google": {
      "display": {
        "family": "Space Grotesk",
        "weights": [400, 500, 600, 700],
        "usage": "H1/H2, section titles, dashboard headlines"
      },
      "body": {
        "family": "IBM Plex Sans",
        "weights": [400, 500, 600],
        "usage": "UI body, forms, tables"
      },
      "numeric": {
        "family": "IBM Plex Mono",
        "weights": [400, 500, 600],
        "usage": "meters, money, timestamps, IDs"
      }
    },

    "typography_scale_tailwind": {
      "h1": "text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight",
      "h2": "text-base md:text-lg font-medium text-muted-foreground",
      "section_title": "text-lg md:text-xl font-semibold tracking-tight",
      "card_title": "text-sm font-semibold",
      "body": "text-sm md:text-base",
      "small": "text-xs",
      "numeric": "font-mono tabular-nums"
    },

    "spacing_system": {
      "rule": "Use 2–3x more spacing than feels comfortable. Prefer 24/32/40px gaps between major blocks.",
      "container": "px-4 sm:px-6 lg:px-8",
      "page_max": "max-w-[1400px]",
      "bento_gap": "gap-4 md:gap-6",
      "card_padding": "p-4 md:p-6",
      "touch_targets": "min-h-11 min-w-11 (driver: min-h-14)"
    },

    "radius_shadow": {
      "radius": {
        "sm": "6px",
        "md": "10px",
        "lg": "14px",
        "pill": "9999px"
      },
      "shadow": {
        "card": "0 1px 0 rgba(16,24,40,.04), 0 10px 30px rgba(16,24,40,.08)",
        "lift": "0 12px 40px rgba(2,6,23,.18)",
        "focus": "0 0 0 4px rgba(45,212,191,.22)"
      }
    },

    "color_system": {
      "mode": "light-first with a deep-ink dispatcher shell option (no transparent backgrounds)",
      "css_vars_hsl": {
        "background": "210 25% 98%",
        "foreground": "222 47% 11%",

        "card": "0 0% 100%",
        "card-foreground": "222 47% 11%",

        "muted": "210 20% 96%",
        "muted-foreground": "215 16% 35%",

        "border": "214 20% 90%",
        "input": "214 20% 90%",

        "primary": "222 47% 11%",
        "primary-foreground": "210 40% 98%",

        "accent": "173 80% 36%",
        "accent-foreground": "210 40% 98%",

        "ring": "173 80% 36%",

        "success": "158 64% 34%",
        "warning": "32 95% 44%",
        "danger": "0 84% 60%",
        "info": "199 89% 48%",

        "ink": "222 47% 11%",
        "ink-2": "222 35% 16%",
        "surface": "210 25% 98%",
        "surface-2": "210 20% 96%"
      },

      "dispatcher_shell_optional": {
        "note": "Use for the app shell only (sidebar/topbar). Keep content cards white for readability.",
        "shell_bg": "222 47% 8%",
        "shell_fg": "210 40% 98%",
        "shell_muted": "215 20% 18%",
        "shell_border": "215 20% 22%"
      },

      "status_chip_palette": {
        "on_site": { "bg": "hsl(199 89% 96%)", "fg": "hsl(199 89% 28%)", "dot": "hsl(199 89% 48%)" },
        "billable": { "bg": "hsl(158 64% 95%)", "fg": "hsl(158 64% 24%)", "dot": "hsl(158 64% 34%)" },
        "notice_sent": { "bg": "hsl(173 80% 95%)", "fg": "hsl(173 80% 22%)", "dot": "hsl(173 80% 36%)" },
        "invoiced": { "bg": "hsl(32 95% 95%)", "fg": "hsl(32 95% 28%)", "dot": "hsl(32 95% 44%)" },
        "paid": { "bg": "hsl(158 64% 95%)", "fg": "hsl(158 64% 24%)", "dot": "hsl(158 64% 34%)" },
        "disputed": { "bg": "hsl(0 84% 96%)", "fg": "hsl(0 84% 34%)", "dot": "hsl(0 84% 60%)" }
      },

      "grade_badges": {
        "A": { "bg": "hsl(158 64% 92%)", "fg": "hsl(158 64% 22%)", "border": "hsl(158 64% 70%)" },
        "B": { "bg": "hsl(173 80% 92%)", "fg": "hsl(173 80% 22%)", "border": "hsl(173 80% 65%)" },
        "C": { "bg": "hsl(199 89% 92%)", "fg": "hsl(199 89% 26%)", "border": "hsl(199 89% 65%)" },
        "D": { "bg": "hsl(32 95% 92%)", "fg": "hsl(32 95% 28%)", "border": "hsl(32 95% 62%)" },
        "F": { "bg": "hsl(0 84% 94%)", "fg": "hsl(0 84% 34%)", "border": "hsl(0 84% 70%)" }
      },

      "allowed_gradients": {
        "rule": "Gradients only as section backgrounds or decorative overlays; never on text-heavy cards; never >20% viewport.",
        "hero_bg": "radial-gradient(900px circle at 20% 10%, rgba(45,212,191,.18), transparent 55%), radial-gradient(700px circle at 80% 0%, rgba(56,189,248,.14), transparent 55%), linear-gradient(180deg, #F8FAFC 0%, #F3F6FA 100%)",
        "map_overlay": "linear-gradient(180deg, rgba(2,6,23,.06) 0%, rgba(2,6,23,0) 55%)"
      },

      "texture": {
        "noise_overlay_css": "background-image: url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22120%22 height=%22120%22%3E%3Cfilter id=%22n%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.9%22 numOctaves=%222%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22120%22 height=%22120%22 filter=%22url(%23n)%22 opacity=%220.08%22/%3E%3C/svg%3E');",
        "usage": "Apply to large section backgrounds only (landing hero, dashboard shell header). Keep opacity <= 0.08."
      }
    }
  },

  "layout": {
    "grid": {
      "dashboard": "12-col desktop bento; 4-col mobile. Map spans 12 on mobile, 7–8 on desktop.",
      "tables": "Use sticky header + horizontal scroll on mobile via ScrollArea.",
      "app_shell": "Sidebar 260px (collapsed 72px). Topbar 56px. Content max-w-[1400px]."
    },

    "page_patterns": {
      "dispatcher_dashboard": [
        "Top: Monday headline card (full width) with 2-line summary + CTA buttons",
        "Left: Live map (primary) with truck markers + legend",
        "Right: Live meters stack (active stops) + Needs attention queue",
        "Bottom: KPI cards (billable $, hours detained, notices pending, invoices ready)"
      ],
      "driver_mobile": [
        "Single-column, thumb-first",
        "Top: facility name + status chip + big timer",
        "Primary actions: ARRIVED / DEPARTED / UPLOAD BOL (large buttons)",
        "Secondary: call dispatcher, view terms"
      ],
      "broker_evidence": [
        "Exhibit header (Load #, Carrier, Facility, Date range)",
        "Two-column desktop: left evidence timeline + clause; right map + BOL photo",
        "Footer: Pay by card + Download PDF + Notice log"
      ]
    }
  },

  "components": {
    "component_path": {
      "core": [
        "/app/frontend/src/components/ui/button.jsx",
        "/app/frontend/src/components/ui/card.jsx",
        "/app/frontend/src/components/ui/badge.jsx",
        "/app/frontend/src/components/ui/tabs.jsx",
        "/app/frontend/src/components/ui/table.jsx",
        "/app/frontend/src/components/ui/dialog.jsx",
        "/app/frontend/src/components/ui/drawer.jsx",
        "/app/frontend/src/components/ui/sheet.jsx",
        "/app/frontend/src/components/ui/scroll-area.jsx",
        "/app/frontend/src/components/ui/separator.jsx",
        "/app/frontend/src/components/ui/tooltip.jsx",
        "/app/frontend/src/components/ui/progress.jsx",
        "/app/frontend/src/components/ui/skeleton.jsx",
        "/app/frontend/src/components/ui/sonner.jsx",
        "/app/frontend/src/components/ui/calendar.jsx",
        "/app/frontend/src/components/ui/input.jsx",
        "/app/frontend/src/components/ui/textarea.jsx",
        "/app/frontend/src/components/ui/select.jsx",
        "/app/frontend/src/components/ui/switch.jsx",
        "/app/frontend/src/components/ui/dropdown-menu.jsx"
      ],
      "recommended_new_components_js": [
        "src/components/meter/DetentionMeter.js",
        "src/components/map/TruckMap.js",
        "src/components/playback/TrailPlayback.js",
        "src/components/status/StatusChip.js",
        "src/components/scorecard/GradeBadge.js",
        "src/components/evidence/EvidenceSeal.js",
        "src/components/pdf/PdfDropzone.js"
      ]
    },

    "buttons": {
      "style": "Professional / Corporate with instrument-panel crispness",
      "tokens": {
        "--btn-radius": "10px",
        "--btn-shadow": "0 1px 0 rgba(16,24,40,.04), 0 10px 30px rgba(16,24,40,.08)",
        "--btn-press-scale": "0.98"
      },
      "variants": {
        "primary": "bg-primary text-primary-foreground hover:bg-primary/92 focus-visible:ring-[hsl(var(--ring))]",
        "secondary": "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        "ghost": "hover:bg-accent/10 hover:text-foreground",
        "danger": "bg-[hsl(var(--danger))] text-white hover:bg-[hsl(var(--danger))]/90"
      },
      "micro_interactions": [
        "Hover: subtle lift (translate-y-[-1px]) + shadow increase",
        "Active: scale to 0.98",
        "Loading: inline spinner left of label; keep width stable"
      ]
    },

    "status_chips": {
      "base": "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium",
      "dot": "h-2 w-2 rounded-full",
      "behavior": [
        "If status is live (On site / Billable ticking): dot uses pulse animation (opacity + scale) every 1.6s",
        "Never use flashing; respect prefers-reduced-motion"
      ]
    },

    "detention_meter": {
      "visual": "Taxi-meter meets industrial instrumentation: big money + small time + segmented progress cells.",
      "layout": [
        "Top row: Facility + Load ID (mono)",
        "Middle: $ billable (mono, large) + rate ($/hr) + cap",
        "Bottom: segmented bar showing free time consumed -> billable -> capped"
      ],
      "segmented_cells": {
        "spec": "Render 60 cells (1 per minute) for the next hour; beyond that show condensed 10-min cells.",
        "colors": {
          "free": "bg-muted",
          "approaching": "bg-[hsl(var(--warning))]/25",
          "billable": "bg-[hsl(var(--success))]/25",
          "capped": "bg-[hsl(var(--danger))]/20"
        }
      },
      "ticking": {
        "animation": "Update numeric values every 1s; animate digit roll only on the cents/seconds columns (CSS translateY).",
        "accessibility": "Provide aria-live=polite summary like 'Billable detention $120.50, 2 hours 10 minutes.'"
      }
    },

    "pdf_extraction_review": {
      "pattern": "Dropzone -> extracting state -> review form with confidence flags.",
      "low_confidence": {
        "ui": "Inline callout row with warning chip + 'Review' anchor; highlight extracted clause with a left border.",
        "highlight": "Use a pale teal marker background (accent/10) behind verbatim clause; never neon."
      }
    },

    "tables_scorecard": {
      "table": "Use shadcn Table + sticky header; first column pinned on desktop.",
      "grade_badge": "Rounded-md badge with border; letter in mono; include tooltip explaining grade formula.",
      "sorting": "Use DropdownMenu for sort presets; keep column sort icons subtle."
    },

    "evidence_exhibit": {
      "tone": "Neutral, court-ready: white cards, clear labels, mono timestamps, minimal color.",
      "evidence_seal": {
        "states": {
          "verified": "Green check + 'Evidence fingerprint verified'",
          "changed": "Red alert + 'Evidence changed since first notice'"
        },
        "visual": "Stamp-like rectangle with microtext border; no transparency."
      }
    },

    "map_leaflet": {
      "style": {
        "tiles": "Use a light, low-contrast OSM tile layer; add a subtle top overlay gradient for depth.",
        "route": "Polyline: stroke #0F766E (teal-700), weight 4, opacity 0.85; outline stroke #99F6E4 at 0.35",
        "geofence": "Circle: stroke #F59E0B (amber-500) at 0.9, fill #F59E0B at 0.12",
        "markers": "Use custom divIcon: status dot + ring; active truck has pulsing ring"
      },
      "legend": "Bottom-left legend card with chips: On site, Billable, Notice sent, Invoiced, Paid, Disputed.",
      "interaction": [
        "Scroll zoom disabled by default on dashboard; enable on click/focus",
        "Playback scrubbing updates marker position without re-centering unless user toggles 'Follow truck'"
      ]
    },

    "trail_playback": {
      "controls": {
        "rail": "Full-width scrubber with event markers (arrival, free-time end, notice sent, departure).",
        "buttons": "Play/Pause, speed (1x/10x/60x) as ToggleGroup, Follow toggle, Jump to events dropdown.",
        "style": "Instrument look: mono timecode, subtle inset border, large hit targets."
      },
      "event_markers": {
        "arrival": "info",
        "free_time_end": "warning",
        "notice_sent": "accent",
        "departure": "success"
      },
      "micro_interactions": [
        "Scrub thumb grows from 12px to 16px on drag",
        "Event marker hover shows Tooltip with timestamp + label",
        "Speed change uses a quick highlight sweep (200ms)"
      ]
    }
  },

  "motion": {
    "library": {
      "recommend": "framer-motion",
      "install": "npm i framer-motion",
      "usage": "Use for page transitions (subtle), meter entrance, attention queue reorder. Respect prefers-reduced-motion."
    },
    "principles": [
      "No universal transition: never transition: all",
      "Use 150–220ms for hover/focus, 280–420ms for layout shifts",
      "Easing: cubic-bezier(0.2, 0.8, 0.2, 1)"
    ]
  },

  "accessibility": {
    "aa": true,
    "rules": [
      "All controls must have visible focus (ring + offset).",
      "Use tabular-nums for money/time to prevent layout shift.",
      "Driver page: minimum 16px body, 56px primary buttons, high contrast in sunlight.",
      "Provide text alternatives for map-only info (timeline list mirrors events)."
    ]
  },

  "testing": {
    "data_testid": {
      "rule": "Every interactive and key informational element MUST include data-testid in kebab-case.",
      "examples": [
        "data-testid=\"dashboard-monday-headline\"",
        "data-testid=\"load-new-pdf-dropzone\"",
        "data-testid=\"detention-meter-billable-amount\"",
        "data-testid=\"driver-arrived-button\"",
        "data-testid=\"broker-pay-by-card-button\"",
        "data-testid=\"playback-speed-10x-toggle\""
      ]
    }
  },

  "image_urls": [
    {
      "category": "landing_hero",
      "description": "Aerial logistics facility image for hero side panel / background card (use with mild overlay, not full-bleed).",
      "url": "https://images.unsplash.com/photo-1564631056585-21000e9a7370?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NTYxNzV8MHwxfHNlYXJjaHwxfHx0cnVjayUyMHlhcmQlMjBhZXJpYWwlMjB2aWV3JTIwbG9naXN0aWNzJTIwZmFjaWxpdHl8ZW58MHx8fHRlYWx8MTc5Mjg3MzMyMnww&ixlib=rb-4.1.0&q=85"
    },
    {
      "category": "landing_support",
      "description": "Industrial truck grid photo for secondary section (scorecard / evidence).",
      "url": "https://images.pexels.com/photos/35501718/pexels-photo-35501718.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"
    },
    {
      "category": "driver_context",
      "description": "Driver/sunlight context image for landing 'No app needed' section (use as small card image).",
      "url": "https://images.unsplash.com/photo-1569020569118-e5cb69d8251b?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NzR8MHwxfHNlYXJjaHwxfHx0cnVjayUyMGRyaXZlciUyMHNtYXJ0cGhvbmUlMjBoYW5kJTIwc3VubGlnaHR8ZW58MHx8fG9yYW5nZXwxNzkyODczMzI0fDA&ixlib=rb-4.1.0&q=85"
    },
    {
      "category": "evidence_packet",
      "description": "Paperwork desk close-up for evidence/invoice packet section (use grayscale, small).",
      "url": "https://images.pexels.com/photos/7680681/pexels-photo-7680681.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"
    }
  ],

  "instructions_to_main_agent": {
    "global_css_updates": [
      "Replace CRA default App.css styles; do NOT center the app container.",
      "In index.css :root, override shadcn tokens with the HSL values above and add success/warning/info vars.",
      "Add font-family CSS vars: --font-display, --font-body, --font-mono; set body to --font-body; headings to --font-display; numeric to --font-mono.",
      "Add .tabular-nums utility if not present: font-variant-numeric: tabular-nums;"
    ],
    "page_specific": [
      "Dispatcher dashboard: map is primary; meters are secondary but visually loud for money/time.",
      "Driver page: mobile-only, no sidebar; use large buttons and high-contrast chips.",
      "Broker evidence: neutral exhibit layout; minimal color; emphasize verification seal + download/pay CTAs."
    ],
    "libraries": [
      "framer-motion for micro-interactions and attention queue reorder",
      "react-leaflet already present; implement custom divIcon markers for status + pulse ring"
    ],
    "do_not": [
      "No transparent backgrounds.",
      "No purple color for AI/chat vibes.",
      "No dark/saturated gradients; keep gradients decorative and under 20% viewport.",
      "Never use transition: all."
    ]
  },

  "general_ui_ux_design_guidelines_appendix": "<General UI UX Design Guidelines>  \n    - You must **not** apply universal transition. Eg: `transition: all`. This results in breaking transforms. Always add transitions for specific interactive elements like button, input excluding transforms\n    - You must **not** center align the app container, ie do not add `.App { text-align: center; }` in the css file. This disrupts the human natural reading flow of text\n   - NEVER: use AI assistant Emoji characters like`🤖🧠💭💡🔮🎯📚🎭🎬🎪🎉🎊🎁🎀🎂🍰🎈🎨🎰💰💵💳🏦💎🪙💸🤑📊📈📉💹🔢🏆🥇 etc for icons. Always use **FontAwesome cdn** or **lucid-react** library already installed in the package.json\n\n **GRADIENT RESTRICTION RULE**\nNEVER use dark/saturated gradient combos (e.g., purple/pink) on any UI element.  Prohibited gradients: blue-500 to purple 600, purple 500 to pink-500, green-500 to blue-500, red to pink etc\nNEVER use dark gradients for logo, testimonial, footer etc\nNEVER let gradients cover more than 20% of the viewport.\nNEVER apply gradients to text-heavy content or reading areas.\nNEVER use gradients on small UI elements (<100px width).\nNEVER stack multiple gradient layers in the same viewport.\n\n**ENFORCEMENT RULE:**\n    • Id gradient area exceeds 20% of viewport OR affects readability, **THEN** use solid colors\n\n**How and where to use:**\n   • Section backgrounds (not content backgrounds)\n   • Hero section header content. Eg: dark to light to dark color\n   • Decorative overlays and accent elements only\n   • Hero section with 2-3 mild color\n   • Gradients creation can be done for any angle say horizontal, vertical or diagonal\n\n- For AI chat, voice application, **do not use purple color. Use color like light green, ocean blue, peach orange etc**\n\n</Font Guidelines>\n\n- Every interaction needs micro-animations - hover states, transitions, parallax effects, and entrance animations. Static = dead. \n   \n- Use 2-3x more spacing than feels comfortable. Cramped designs look cheap.\n\n- Subtle grain textures, noise overlays, custom cursors, selection states, and loading animations: separates good from extraordinary.\n   \n- Before generating UI, infer the visual style from the problem statement (palette, contrast, mood, motion) and immediately instantiate it by setting global design tokens (primary, secondary/accent, background, foreground, ring, state colors), rather than relying on any library defaults. Don't make the background dark as a default step, always understand problem first and define colors accordingly\n    Eg: - if it implies playful/energetic, choose a colorful scheme\n           - if it implies monochrome/minimal, choose a black–white/neutral scheme\n\n**Component Reuse:**\n\t- Prioritize using pre-existing components from src/components/ui when applicable\n\t- Create new components that match the style and conventions of existing components when needed\n\t- Examine existing components to understand the project's component patterns before creating new ones\n\n**IMPORTANT**: Do not use HTML based component like dropdown, calendar, toast etc. You **MUST** always use `/app/frontend/src/components/ui/ ` only as a primary components as these are modern and stylish component\n\n**Best Practices:**\n\t- Use Shadcn/UI as the primary component library for consistency and accessibility\n\t- Import path: ./components/[component-name]\n\n**Export Conventions:**\n\t- Components MUST use named exports (export const ComponentName = ...)\n\t- Pages MUST use default exports (export default function PageName() {...})\n\n**Toasts:**\n  - Use `sonner` for toasts\"\n  - Sonner component are located in `/app/src/components/ui/sonner.tsx`\n\nUse 2–4 color gradients, subtle textures/noise overlays, or CSS-based noise to avoid flat visuals.\n</General UI UX Design Guidelines>"
}
