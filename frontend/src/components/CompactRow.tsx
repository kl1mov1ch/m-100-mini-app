import { Button, Modal } from 'antd';
import { ChevronRight } from 'lucide-react';
import { useState, type ReactNode } from 'react';

export type CompactRowProps = {
	title: string;
	description?: ReactNode;
	value?: ReactNode;
	meta?: ReactNode;
	leading?: ReactNode;
	attention?: boolean;
	status?: 'pending' | 'sent';
	className?: string;
	dialog?: boolean;
	onClick: () => void;
};

export function CompactRow({
	title,
	description,
	value,
	meta,
	leading,
	attention,
	status,
	className = '',
	dialog = true,
	onClick,
}: CompactRowProps) {
	return (
		<button
			type="button"
			className={`compact-row ${attention ? 'compact-row-attention' : ''} ${status ? 'compact-row-' + status : ''} ${className}`}
			onClick={onClick}
			title={title}
			aria-haspopup={dialog ? 'dialog' : undefined}
		>
			{leading && <span className="compact-row-leading">{leading}</span>}
			<span className="compact-row-main">
				<strong>{title}</strong>
				{description && <span className="compact-row-description">{description}</span>}
			</span>
			{(value != null || meta) && (
				<span className="compact-row-aside">
					{value != null && <strong>{value}</strong>}
					{meta && <span>{meta}</span>}
				</span>
			)}
			<ChevronRight className="compact-row-arrow" size={16} aria-hidden />
		</button>
	);
}

export function CompactWorkEditor({
	children,
	hint,
	footer,
	...props
}: Omit<CompactRowProps, 'onClick'> & { children: ReactNode; hint?: string; footer?: ReactNode }) {
	const [open, setOpen] = useState(false);
	const [present, setPresent] = useState(false);
	return (
		<>
			<CompactRow
				{...props}
				onClick={() => {
					setPresent(true);
					setOpen(true);
				}}
			/>
			{present && (
				<Modal
					className="compact-work-sheet"
					title={props.title}
					open={open}
					destroyOnHidden
					afterClose={() => setPresent(false)}
					onCancel={() => setOpen(false)}
					footer={
						footer === undefined ? (
							<Button type="primary" onClick={() => setOpen(false)}>
								Готово
							</Button>
						) : (
							footer
						)
					}
				>
					<div className="compact-work-content">{children}</div>
					{hint && <p className="compact-work-hint">{hint}</p>}
				</Modal>
			)}
		</>
	);
}
