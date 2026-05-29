import React from 'react';
import { OllamaModel } from '../types';

interface Props {
  models: OllamaModel[];
  selectedModel: string;
  onChange: (model: string) => void;
}

export default function ModelSelector({ models, selectedModel, onChange }: Props) {
  return (
    <div className="model-selector">
      <label>모델:</label>
      <select value={selectedModel} onChange={(e) => onChange(e.target.value)}>
        {models.map((m) => (
          <option key={m.name} value={m.name}>
            {m.name}
          </option>
        ))}
      </select>
    </div>
  );
}
