import { DatePicker as AntDatePicker } from 'antd';
import type { DatePickerProps } from 'antd';
import { cloneElement, isValidElement, useState } from 'react';
import type { ReactElement } from 'react';
import dayjs from '../lib/date';
import { useHorizontalSwipe } from '../hooks/useHorizontalSwipe';

export function DatePicker({
	workDates = [],
	...props
}: DatePickerProps & { workDates?: string[] }) {
	const markedDays = new Set(workDates);
	const [month, setMonth] = useState(() => props.value || dayjs());
	const [mode, setMode] = useState('date');
	const swipe = useHorizontalSwipe(
		(step) => setMonth((current) => current.add(step, 'month')),
		mode !== 'date',
	);
	return (
		<AntDatePicker
			{...props}
			inputReadOnly
			pickerValue={month}
			onPickerValueChange={setMonth}
			onOpenChange={(open) => {
				if (open) {
					setMonth(props.value || dayjs());
					setMode('date');
				}
				props.onOpenChange?.(open);
			}}
			onPanelChange={(value, panelMode) => {
				setMode(panelMode);
				props.onPanelChange?.(value, panelMode);
			}}
			panelRender={(panel) => (
				<div className="swipe-surface" {...swipe}>
					{props.panelRender ? props.panelRender(panel) : panel}
				</div>
			)}
			cellRender={(current, info) => {
				if (
					info.type !== 'date' ||
					typeof current === 'number' ||
					typeof current === 'string' ||
					!markedDays.has(current.format('YYYY-MM-DD')) ||
					!isValidElement(info.originNode)
				)
					return info.originNode;
				const original = info.originNode as ReactElement<{ className?: string; title?: string }>;
				return cloneElement(original, {
					className: (original.props.className || '') + ' has-work-on-date',
					title: 'В этот день выполнялись работы',
				});
			}}
			renderExtraFooter={
				workDates.length
					? () => (
							<span className="calendar-work-legend">
								<i />
								Есть выполненные работы
							</span>
						)
					: undefined
			}
		/>
	);
}
