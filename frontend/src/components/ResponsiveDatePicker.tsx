import { DatePicker as AntDatePicker } from 'antd';
import type { DatePickerProps } from 'antd';
import { cloneElement, isValidElement } from 'react';
import type { ReactElement } from 'react';

export function DatePicker({
	workDates = [],
	...props
}: DatePickerProps & { workDates?: string[] }) {
	const markedDays = new Set(workDates);
	return (
		<AntDatePicker
			{...props}
			inputReadOnly
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
