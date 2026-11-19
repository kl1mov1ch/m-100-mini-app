import { Cell } from '@telegram-apps/telegram-ui';
import { Button } from './Button';
import { SheetModal as Modal } from './SheetModal';
import { ChevronRight } from './kit-icons';
import { useState, type ReactNode } from 'react';
import type { reportStatus } from './SyncStatus';

export type CompactRowProps = {
	title: string;
	description?: ReactNode;
	value?: ReactNode;
	meta?: ReactNode;
	leading?: ReactNode;
	attention?: boolean;
	status?: ReturnType<typeof reportStatus>;
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
		<Cell
			Component="button"
			multiline
			type="button"
			className={`compact-row ${attention ? 'compact-row-attention' : ''} ${status ? 'compact-row-' + status : ''} ${className}`}
			onClick={onClick}
			title={title}
			aria-haspopup={dialog ? 'dialog' : undefined}
			before={leading && <span className="compact-row-leading">{leading}</span>}
			subtitle={description && <span className="compact-row-description">{description}</span>}
			after={
				<span className="compact-row-end">
					{(value != null || meta) && (
						<span className="compact-row-aside">
							{value != null && <strong>{value}</strong>}
							{meta && <span>{meta}</span>}
						</span>
					)}
					<ChevronRight className="compact-row-arrow" size={16} aria-hidden />
				</span>
			}
		>
			<span className="compact-row-main">
				<strong>{title}</strong>
			</span>
		</Cell>
	);
}

export function CompactWorkEditor({
	children,
	hint,
	footer,
	modalClassName,
	modalTitle,
	...props
}: Omit<CompactRowProps, 'onClick'> & {
	children: ReactNode | ((close: () => void) => ReactNode);
	hint?: string;
	footer?: ReactNode;
	modalClassName?: string;
	modalTitle?: string;
}) {
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
					className={modalClassName ? 'compact-work-sheet ' + modalClassName : 'compact-work-sheet'}
					title={modalTitle || props.title}
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
					<div className="compact-work-content">
						{typeof children === 'function' ? children(() => setOpen(false)) : children}
					</div>
					{hint && <p className="compact-work-hint">{hint}</p>}
				</Modal>
			)}
		</>
	);
}
