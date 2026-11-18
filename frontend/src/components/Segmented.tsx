import { SegmentedControl } from '@telegram-apps/telegram-ui';
import type { ReactNode } from 'react';

export function Segmented<T extends string>({
	options,
	value,
	onChange,
	block,
	disabled,
	className = '',
	'aria-label': label,
}: {
	options: readonly { value: T; label: ReactNode }[];
	value: T;
	onChange: (value: T) => void;
	block?: boolean;
	disabled?: boolean;
	className?: string;
	'aria-label'?: string;
}) {
	return (
		<SegmentedControl
			className={className + (block ? ' m100-segmented-block' : '')}
			role="radiogroup"
			aria-label={label}
			onKeyDown={(event) => {
				const step = ['ArrowRight', 'ArrowDown'].includes(event.key)
					? 1
					: ['ArrowLeft', 'ArrowUp'].includes(event.key)
						? -1
						: 0;
				if (disabled || !step) return;
				event.preventDefault();
				const current = options.findIndex((item) => item.value === value);
				const next = (current + step + options.length) % options.length;
				onChange(options[next].value);
				event.currentTarget.querySelectorAll('button')[next]?.focus();
			}}
		>
			{options.map((option) => (
				<SegmentedControl.Item
					key={option.value}
					type="button"
					role="radio"
					aria-checked={option.value === value}
					selected={option.value === value}
					tabIndex={option.value === value ? 0 : -1}
					disabled={disabled}
					onClick={() => onChange(option.value)}
				>
					{option.label}
				</SegmentedControl.Item>
			))}
		</SegmentedControl>
	);
}
