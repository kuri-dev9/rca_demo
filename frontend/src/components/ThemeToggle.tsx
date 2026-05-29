import React from 'react';

interface Props {
  dark: boolean;
  onToggle: () => void;
}

export default function ThemeToggle({ dark, onToggle }: Props) {
  return (
    <button className="theme-toggle" onClick={onToggle} title="테마 전환">
      <img src={dark ? '/light_mode_icon.svg' : '/dark_mode_icon.svg'} alt="테마" className="btn-icon" />
    </button>
  );
}
