import { Button, Calendar, Modal } from 'antd';
import type { Dayjs } from 'dayjs';
import { CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { useId, useState } from 'react';
import dayjs from '../lib/date';
import { useHorizontalSwipe } from '../hooks/useHorizontalSwipe';
import './responsive-date-picker.css';

type DatePickerProps = {
	'aria-label'?: string;
	value: Dayjs | null;
	format?: string;
	placeholder?: string;
	allowClear?: boolean;
	workDates?: string[];
	disabledDate?: (date: Dayjs) => boolean;
	onChange: (date: Dayjs | null) => void;
};

export function DatePicker({
	'aria-label': label = 'Выбрать дату',
	value,
	format = 'DD.MM.YYYY',
	placeholder = 'Выбрать дату',
	allowClear = true,
	workDates = [],
	disabledDate,
	onChange,
}: DatePickerProps) {
	const id = useId();
	const [open, setOpen] = useState(false);
	const [cursor, setCursor] = useState(() => value || dayjs());
	const [mode, setMode] = useState<'month' | 'year'>('month');
	const markedDays = new Set(workDates);
	const today = dayjs();
	const move = (step: number) => setCursor((current) => current.add(step, mode));
	const swipe = useHorizontalSwipe(move, mode !== 'month');

	const choose = (date: Dayjs | null) => {
		if (date && disabledDate?.(date)) return;
		setOpen(false);
		if (!date || !date.isSame(value, 'day')) onChange(date);
	};

	return (
		<div className="date-control">
			<Button
				className="date-control-trigger"
				aria-label={label + (value ? ', ' + value.format(format) : '')}
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? id : undefined}
				onClick={() => {
					setCursor(value || today);
					setMode('month');
					setOpen(true);
				}}
			>
				<span>{value?.format(format) || placeholder}</span>
				<CalendarDays size={17} aria-hidden />
			</Button>
			{allowClear && value && (
				<Button
					type="text"
					className="date-control-clear"
					aria-label={'Очистить: ' + label}
					icon={<X size={16} />}
					onClick={() => choose(null)}
				/>
			)}
			<Modal
				title={label}
				open={open}
				onCancel={() => setOpen(false)}
				footer={null}
				rootClassName="date-control-modal"
			>
				<div id={id} className="swipe-surface" {...swipe}>
					<Calendar
						fullscreen={false}
						mode={mode}
						value={cursor}
						disabledDate={mode === 'month' ? disabledDate : undefined}
						headerRender={() => (
							<div className="date-control-header">
								<Button
									type="text"
									aria-label="Назад"
									icon={<ChevronLeft size={20} />}
									onClick={() => move(-1)}
								/>
								<Button type="text" onClick={() => setMode(mode === 'month' ? 'year' : 'month')}>
									{cursor.format(mode === 'month' ? 'MMMM YYYY' : 'YYYY')}
								</Button>
								<Button
									type="text"
									aria-label="Вперёд"
									icon={<ChevronRight size={20} />}
									onClick={() => move(1)}
								/>
							</div>
						)}
						onSelect={(date, info) => {
							if (info.source === 'date') choose(date);
							if (info.source === 'month') {
								setCursor(date);
								setMode('month');
							}
						}}
						fullCellRender={(date, info) => {
							const isDay = info.type === 'date';
							const selected = isDay && date.isSame(value, 'day');
							const marked = isDay && markedDays.has(date.format('YYYY-MM-DD'));
							const disabled = isDay && !!disabledDate?.(date);
							return (
								<button
									type="button"
									className="date-control-cell"
									aria-label={
										date.format(isDay ? 'D MMMM YYYY' : 'MMMM YYYY') +
										(marked ? ', есть работы' : '')
									}
									aria-current={isDay && date.isSame(today, 'day') ? 'date' : undefined}
									aria-pressed={selected}
									data-work={marked || undefined}
									disabled={disabled}
								>
									{date.format(isDay ? 'D' : 'MMM')}
								</button>
							);
						}}
					/>
					<div className="date-control-footer">
						{workDates.length > 0 && (
							<span className="calendar-work-legend">
								<i /> Есть работы
							</span>
						)}
						<Button type="text" disabled={disabledDate?.(today)} onClick={() => choose(today)}>
							Сегодня
						</Button>
					</div>
				</div>
			</Modal>
		</div>
	);
}
