"use client";

import React, { useState, useEffect } from "react";

interface AnimatedAiMascotProps {
  isThinking?: boolean;
  className?: string;
}

export function AnimatedAiMascot({ isThinking = false, className = "" }: AnimatedAiMascotProps) {
  const [isBlinking, setIsBlinking] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  // Periodic natural blinking with occasional double-blink
  useEffect(() => {
    let timeoutId: NodeJS.Timeout;
    const interval = setInterval(() => {
      setIsBlinking(true);
      timeoutId = setTimeout(() => {
        setIsBlinking(false);
        // 30% chance of an inquisitive double-blink
        if (Math.random() > 0.7) {
          setTimeout(() => {
            setIsBlinking(true);
            setTimeout(() => setIsBlinking(false), 160);
          }, 140);
        }
      }, 180);
    }, 4500);

    return () => {
      clearInterval(interval);
      clearTimeout(timeoutId);
    };
  }, []);

  return (
    <div
      className={`relative w-full h-40 flex items-center justify-center select-none overflow-hidden rounded-2xl bg-gradient-to-b from-[#EDE8D8]/60 via-[#EDE8D8]/25 to-transparent transition-colors duration-500 ${className}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      role="img"
      aria-label="RollCall AI 3D Interactive Mascot"
    >
      {/* Background Holographic Stage & Golden Atmosphere */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none overflow-hidden">
        {/* Soft Radial Ambient Spotlight */}
        <div
          className={`w-48 h-48 rounded-full bg-gradient-to-tr from-[#6C5119]/15 via-[#A77A13]/25 to-transparent blur-2xl transition-all duration-700 ${
            isThinking ? "scale-130 opacity-90" : isHovered ? "scale-115 opacity-75" : "scale-100 opacity-45"
          }`}
        />

        {/* Dynamic Concentric AI Pulse Rings */}
        <div
          className={`absolute w-36 h-36 rounded-full border border-[#A77A13]/30 transition-all duration-700 ${
            isThinking ? "animate-ping opacity-40" : isHovered ? "scale-105 opacity-30" : "animate-pulse opacity-20"
          }`}
          style={{ animationDuration: isThinking ? "1.5s" : "4s" }}
        />
        <div
          className={`absolute w-52 h-52 rounded-full border border-[#6C5119]/15 transition-all duration-1000 ${
            isThinking ? "scale-110 opacity-35" : "opacity-15"
          }`}
        />

        {/* Subtle Horizontal Soundwave Horizon */}
        <div className="absolute bottom-6 w-3/4 h-[1px] bg-gradient-to-r from-transparent via-[#6C5119]/25 to-transparent" />
      </div>

      {/* Floating Golden Ambient Sparkles */}
      <span
        className="absolute top-3 left-9 text-[#A77A13] text-xs font-serif animate-bounce pointer-events-none drop-shadow-xs"
        style={{ animationDuration: "3s" }}
      >
        ✦
      </span>
      <span
        className="absolute bottom-6 right-10 text-[#6C5119] text-sm animate-pulse pointer-events-none"
        style={{ animationDuration: "2.4s" }}
      >
        ✧
      </span>
      <span
        className="absolute top-6 right-12 text-[#A77A13]/80 text-[11px] pointer-events-none animate-ping"
        style={{ animationDuration: "4s" }}
      >
        ✦
      </span>
      <span
        className="absolute bottom-10 left-12 text-[#6C5119]/60 text-[9px] pointer-events-none animate-pulse"
        style={{ animationDuration: "3.2s" }}
      >
        ✧
      </span>

      {/* Interactive 3D Robot Mascot Assembly */}
      <div
        className="relative z-10 flex flex-col items-center cursor-pointer will-change-transform"
        style={{
          animation: isThinking
            ? "mascotThink 1.4s ease-in-out infinite"
            : isHovered
            ? "mascotHoverFloat 2.8s ease-in-out infinite"
            : "mascotFloat 4s ease-in-out infinite",
        }}
      >
        {/* Hardware-accelerated CSS Keyframes */}
        <style jsx>{`
          @keyframes mascotFloat {
            0%, 100% {
              transform: translate3d(0, 0, 0) rotate(0deg);
            }
            50% {
              transform: translate3d(0, -9px, 0) rotate(1.2deg);
            }
          }
          @keyframes mascotHoverFloat {
            0%, 100% {
              transform: translate3d(0, -4px, 0) rotate(-1deg);
            }
            50% {
              transform: translate3d(0, -12px, 0) rotate(1.8deg);
            }
          }
          @keyframes mascotThink {
            0%, 100% {
              transform: translate3d(0, -2px, 0) scale(1.02);
            }
            50% {
              transform: translate3d(0, -11px, 0) scale(0.98);
            }
          }
          @keyframes shadowBreathe {
            0%, 100% {
              transform: scale3d(1, 1, 1);
              opacity: 0.38;
            }
            50% {
              transform: scale3d(0.72, 0.72, 1);
              opacity: 0.18;
            }
          }
          @keyframes tasselFloat {
            0%, 100% {
              transform: rotate(0deg);
            }
            50% {
              transform: rotate(16deg);
            }
          }
          @keyframes handWave {
            0%, 100% {
              transform: rotate(-18deg) translate3d(0, 0, 0);
            }
            50% {
              transform: rotate(26deg) translate3d(2px, -3px, 0);
            }
          }
          @keyframes leftHandBob {
            0%, 100% {
              transform: translate3d(0, 0, 0);
            }
            50% {
              transform: translate3d(0, -3px, 0);
            }
          }
          @keyframes eyeGlowPulse {
            0%, 100% {
              filter: drop-shadow(0 0 4px #00f2fe) drop-shadow(0 0 10px rgba(0, 242, 254, 0.6));
            }
            50% {
              filter: drop-shadow(0 0 7px #00f2fe) drop-shadow(0 0 16px rgba(0, 229, 255, 0.9));
            }
          }
          @keyframes scanBeam {
            0% {
              transform: translate3d(-30px, 0, 0);
              opacity: 0;
            }
            30% {
              opacity: 1;
            }
            70% {
              opacity: 1;
            }
            100% {
              transform: translate3d(30px, 0, 0);
              opacity: 0;
            }
          }
        `}</style>

        {/* High-Definition 3D Vector Mascot SVG */}
        <svg
          width="120"
          height="124"
          viewBox="0 0 120 124"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="overflow-visible"
        >
          <defs>
            {/* 3D Ceramic Pearl Helmet Radial Shader */}
            <radialGradient id="ceramicHead" cx="36%" cy="28%" r="68%">
              <stop offset="0%" stopColor="#FFFFFF" />
              <stop offset="45%" stopColor="#FBF8F0" />
              <stop offset="78%" stopColor="#EDE4D0" />
              <stop offset="100%" stopColor="#D4C8B0" />
            </radialGradient>

            {/* Pearlescent Body Shader */}
            <radialGradient id="ceramicBody" cx="34%" cy="30%" r="70%">
              <stop offset="0%" stopColor="#FFFFFF" />
              <stop offset="50%" stopColor="#F8F3E6" />
              <stop offset="82%" stopColor="#E2D6BE" />
              <stop offset="100%" stopColor="#C4B495" />
            </radialGradient>

            {/* Rich Metallic Antique Gold Linear Shader */}
            <linearGradient id="richGold" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#FFF3CE" />
              <stop offset="28%" stopColor="#E6C466" />
              <stop offset="65%" stopColor="#B88A22" />
              <stop offset="100%" stopColor="#6C5119" />
            </linearGradient>

            {/* Deep Gold Edge Shader */}
            <linearGradient id="darkGold" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#B88A22" />
              <stop offset="100%" stopColor="#4A370E" />
            </linearGradient>

            {/* Ultra-Glossy Obsidian OLED Visor */}
            <radialGradient id="obsidianVisor" cx="50%" cy="35%" r="75%">
              <stop offset="0%" stopColor="#1C212A" />
              <stop offset="65%" stopColor="#0F1218" />
              <stop offset="100%" stopColor="#050709" />
            </radialGradient>

            {/* Cyan Neon LED Eye Gradient */}
            <linearGradient id="cyanEyeGlow" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#A5F3FC" />
              <stop offset="35%" stopColor="#22D3EE" />
              <stop offset="100%" stopColor="#0284C7" />
            </linearGradient>

            {/* Curved Glass Specular Highlight Arc */}
            <linearGradient id="glassReflection" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.82" />
              <stop offset="40%" stopColor="#FFFFFF" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.0" />
            </linearGradient>

            {/* Subtle Rim Ambient Light */}
            <linearGradient id="rimLight" x1="100%" y1="100%" x2="0%" y2="0%">
              <stop offset="0%" stopColor="#A77A13" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
            </linearGradient>

            {/* Inner Ear Cup Shadow */}
            <radialGradient id="cupShadow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#2A2416" />
              <stop offset="100%" stopColor="#14110A" />
            </radialGradient>
          </defs>

          {/* 1. Academic Graduation Cap with 3D Bevel & Swinging Tassel */}
          <g id="graduation-cap" className="drop-shadow-md">
            {/* Diamond Mortarboard Upper Deck */}
            <path
              d="M 60 11 L 92 20.5 L 60 29.5 L 28 20.5 Z"
              fill="url(#richGold)"
              stroke="#594214"
              strokeWidth="0.7"
            />
            {/* Mortarboard 3D Edge Bevel */}
            <path
              d="M 28 20.5 L 60 29.5 L 60 31.5 L 28 22.5 Z"
              fill="url(#darkGold)"
            />
            <path
              d="M 92 20.5 L 60 29.5 L 60 31.5 L 92 22.5 Z"
              fill="#7A5D19"
            />

            {/* Skullcap Pedestal Base */}
            <ellipse cx="60" cy="24" rx="16" ry="5.5" fill="#523E11" />
            <ellipse cx="60" cy="22.5" rx="15" ry="5" fill="url(#richGold)" />

            {/* Cap Center Button */}
            <circle cx="60" cy="20.2" r="2.4" fill="#FFF3D0" stroke="#7A5D19" strokeWidth="0.6" />

            {/* Hanging Golden Tassel with Inertia Physics */}
            <g
              style={{
                transformOrigin: "60px 20.2px",
                animation: "tasselFloat 3.2s ease-in-out infinite",
              }}
            >
              <path
                d="M 60 21 Q 81 24.5 83 35"
                stroke="#6C5119"
                strokeWidth="1.3"
                fill="none"
                strokeLinecap="round"
              />
              {/* Tassel Golden Ring & Fringe */}
              <circle cx="83" cy="36" r="2" fill="url(#richGold)" />
              <path
                d="M 83 37.5 L 81 44.5 M 83 37.5 L 83 45.5 M 83 37.5 L 85 44.5"
                stroke="#D4AF37"
                strokeWidth="1.3"
                strokeLinecap="round"
              />
            </g>
          </g>

          {/* 2. Golden Headset & Metallic Ear Cushions */}
          <g id="headset">
            {/* Curved Padded Headband Arc */}
            <path
              d="M 25 58 C 25 29 95 29 95 58"
              stroke="url(#richGold)"
              strokeWidth="4"
              fill="none"
              strokeLinecap="round"
              className="drop-shadow-xs"
            />
            {/* Headband Center Grip */}
            <path
              d="M 46 32 C 54 30.5 66 30.5 74 32"
              stroke="#523E11"
              strokeWidth="2.5"
              fill="none"
              strokeLinecap="round"
            />

            {/* Left Metallic Ear-Pad */}
            <g id="left-ear">
              <rect x="18" y="47" width="10" height="22" rx="5" fill="url(#richGold)" stroke="#523E11" strokeWidth="0.8" />
              <rect x="21" y="50" width="4" height="16" rx="2" fill="url(#cupShadow)" />
              {/* LED Ring on Ear-cup */}
              <circle cx="23" cy="58" r="2" fill="#22D3EE" opacity="0.8" />
            </g>

            {/* Right Metallic Ear-Pad */}
            <g id="right-ear">
              <rect x="92" y="47" width="10" height="22" rx="5" fill="url(#richGold)" stroke="#523E11" strokeWidth="0.8" />
              <rect x="95" y="50" width="4" height="16" rx="2" fill="url(#cupShadow)" />
              {/* LED Ring on Ear-cup */}
              <circle cx="97" cy="58" r="2" fill="#22D3EE" opacity="0.8" />
            </g>
          </g>

          {/* 3. Spherical Ceramic Helmet Head */}
          <g id="head">
            {/* Main Smooth Ceramic Helmet Sphere */}
            <rect
              x="27"
              y="30"
              width="66"
              height="55"
              rx="27.5"
              fill="url(#ceramicHead)"
              stroke="#D4AF37"
              strokeWidth="1"
            />
            {/* Helmet Rim Ambient Highlight */}
            <rect
              x="27"
              y="30"
              width="66"
              height="55"
              rx="27.5"
              fill="url(#rimLight)"
            />

            {/* Glossy Obsidian Curved OLED Screen */}
            <rect
              x="33"
              y="37"
              width="54"
              height="40"
              rx="18"
              fill="url(#obsidianVisor)"
              stroke="#1C212A"
              strokeWidth="1.2"
              className="drop-shadow-inner"
            />

            {/* Screen Internal Cyan Glow Halo */}
            <rect
              x="34"
              y="38"
              width="52"
              height="38"
              rx="17"
              fill="none"
              stroke="#22D3EE"
              strokeWidth="0.6"
              opacity="0.35"
            />

            {/* Specular Curved Glass Highlight (Gloss sheen) */}
            <path
              d="M 38 41 C 48 38 72 38 82 41 C 80 49 71 52 39 52 Z"
              fill="url(#glassReflection)"
            />

            {/* Expressive Glowing Cyan LED Visor Display */}
            <g
              id="led-facial-screen"
              style={{ animation: "eyeGlowPulse 2.8s ease-in-out infinite" }}
            >
              {isBlinking ? (
                /* Natural Organic Blink: Flat glowing slits */
                <>
                  <line x1="42" y1="56" x2="53" y2="56" stroke="url(#cyanEyeGlow)" strokeWidth="3" strokeLinecap="round" />
                  <line x1="67" y1="56" x2="78" y2="56" stroke="url(#cyanEyeGlow)" strokeWidth="3" strokeLinecap="round" />
                </>
              ) : isHovered ? (
                /* Joyful Happy Arcs (^ ‿ ^) on Hover */
                <>
                  {/* Left Happy Curved Eye */}
                  <path
                    d="M 42 59 Q 47.5 50 53 59"
                    stroke="url(#cyanEyeGlow)"
                    strokeWidth="3.6"
                    fill="none"
                    strokeLinecap="round"
                  />
                  {/* Right Happy Curved Eye */}
                  <path
                    d="M 67 59 Q 72.5 50 78 59"
                    stroke="url(#cyanEyeGlow)"
                    strokeWidth="3.6"
                    fill="none"
                    strokeLinecap="round"
                  />

                  {/* Cheerful Mouth Smile */}
                  <path
                    d="M 57 65.5 Q 60 68 63 65.5"
                    stroke="url(#cyanEyeGlow)"
                    strokeWidth="2.2"
                    fill="none"
                    strokeLinecap="round"
                  />

                  {/* Cute Glowing Rosy Cheeks */}
                  <circle cx="39" cy="62" r="3" fill="#F43F5E" opacity="0.5" />
                  <circle cx="81" cy="62" r="3" fill="#F43F5E" opacity="0.5" />
                </>
              ) : isThinking ? (
                /* Thinking / Scanning Frequency State */
                <>
                  {/* Pulsing Concentric Circular Scanner Eyes */}
                  <circle cx="47.5" cy="56" r="5" fill="none" stroke="url(#cyanEyeGlow)" strokeWidth="2.2">
                    <animate attributeName="r" values="3.5;6;3.5" dur="1s" repeatCount="indefinite" />
                  </circle>
                  <circle cx="47.5" cy="56" r="2" fill="url(#cyanEyeGlow)" />

                  <circle cx="72.5" cy="56" r="5" fill="none" stroke="url(#cyanEyeGlow)" strokeWidth="2.2">
                    <animate attributeName="r" values="6;3.5;6" dur="1s" repeatCount="indefinite" />
                  </circle>
                  <circle cx="72.5" cy="56" r="2" fill="url(#cyanEyeGlow)" />

                  {/* High-Tech Animated Radar Scan Beam */}
                  <g style={{ animation: "scanBeam 1.6s ease-in-out infinite" }}>
                    <line x1="60" y1="44" x2="60" y2="68" stroke="#67E8F9" strokeWidth="1" opacity="0.8" />
                  </g>
                </>
              ) : (
                /* Default State: Friendly Pill Eyes with Sparkling Pupil Highlights */
                <>
                  {/* Left Pill Eye */}
                  <rect x="42.5" y="49" width="10" height="14" rx="5" fill="url(#cyanEyeGlow)" />
                  <circle cx="45" cy="52" r="2.2" fill="#FFFFFF" opacity="0.95" />
                  <circle cx="48.5" cy="57" r="1.1" fill="#FFFFFF" opacity="0.75" />

                  {/* Right Pill Eye */}
                  <rect x="67.5" y="49" width="10" height="14" rx="5" fill="url(#cyanEyeGlow)" />
                  <circle cx="70" cy="52" r="2.2" fill="#FFFFFF" opacity="0.95" />
                  <circle cx="73.5" cy="57" r="1.1" fill="#FFFFFF" opacity="0.75" />

                  {/* Gentle Confident Mini Smile */}
                  <path
                    d="M 57 65.5 Q 60 67.5 63 65.5"
                    stroke="url(#cyanEyeGlow)"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    fill="none"
                    opacity="0.85"
                  />
                </>
              )}
            </g>
          </g>

          {/* 4. Golden Neck Ring & Pearlescent Ceramic Torso */}
          <g id="torso">
            {/* Metallic Collar Ring */}
            <ellipse cx="60" cy="84" rx="16" ry="4" fill="url(#richGold)" stroke="#594214" strokeWidth="0.8" />

            {/* Egg-Shaped Ceramic Body */}
            <path
              d="M 43 87 C 39 101 46 116 60 116 C 74 116 81 101 77 87 Z"
              fill="url(#ceramicBody)"
              stroke="#D4AF37"
              strokeWidth="1"
            />

            {/* Golden Institutional Core Emblem */}
            <circle cx="60" cy="98" r="6" fill="url(#richGold)" stroke="#594214" strokeWidth="0.7" />
            <path
              d="M 57.5 98 L 59.5 100.5 L 63 95.5"
              stroke="#24251C"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </g>

          {/* 5. Cute Floating Magnetic Hands (Out-of-phase levitation) */}
          <g id="magnetic-hands">
            {/* Left Hand (Idle gentle bob) */}
            <g style={{ animation: "leftHandBob 3.6s ease-in-out infinite" }}>
              <ellipse
                cx="34"
                cy="95"
                rx="4.5"
                ry="7.5"
                transform="rotate(20 34 95)"
                fill="url(#ceramicHead)"
                stroke="#D4AF37"
                strokeWidth="0.9"
                className="drop-shadow-xs"
              />
            </g>

            {/* Right Hand: Waves enthusiastically on hover */}
            <g
              style={{
                transformOrigin: "86px 95px",
                animation: isHovered ? "handWave 0.7s ease-in-out infinite" : "mascotFloat 4s ease-in-out infinite",
              }}
            >
              <ellipse
                cx="86"
                cy="95"
                rx="4.5"
                ry="7.5"
                transform={isHovered ? "rotate(-40 86 95)" : "rotate(-20 86 95)"}
                fill="url(#ceramicHead)"
                stroke="#D4AF37"
                strokeWidth="0.9"
                className="drop-shadow-xs transition-transform duration-300"
              />
            </g>
          </g>
        </svg>

        {/* 6. Dynamic Pedestal Shadow (Scales and blurs in sync with elevation) */}
        <div
          className="w-18 h-3 rounded-full bg-[#6C5119]/30 blur-[3px] mt-0.5 will-change-transform"
          style={{
            animation: "shadowBreathe 4s ease-in-out infinite",
          }}
        />
      </div>
    </div>
  );
}
