import { cn } from "@/lib/utils";

export interface SelectableListItem {
  id: string;
  primary: string;
  secondary: string;
}

export function SelectableList({
  items,
  selectedId,
  onSelect,
  emptyMessage,
}: {
  items: SelectableListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  emptyMessage: string;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;
  }

  return (
    <div className="space-y-1">
      {items.map((item) => (
        <button
          key={item.id}
          onClick={() => onSelect(item.id)}
          className={cn(
            "block w-full rounded-md px-3 py-2 text-left text-sm transition-colors",
            selectedId === item.id ? "bg-accent text-accent-foreground" : "hover:bg-muted",
          )}
        >
          <p className="font-medium">{item.primary}</p>
          <p className="text-xs text-muted-foreground">{item.secondary}</p>
        </button>
      ))}
    </div>
  );
}
