export default function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
  className = "",
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={`segmented ${className}`}>
      {options.map(([id, text]) => (
        <button key={id} type="button" role="tab" aria-selected={value === id} onClick={() => onChange(id)}>
          {text}
        </button>
      ))}
    </div>
  );
}
