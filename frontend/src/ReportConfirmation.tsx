import { Alert } from 'antd';
import { ArrowRight, CloudUpload, Minus, Plus, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import './confirmation.css';
import dayjs from './lib/date';

type ConfirmationPosition = {
	id: string;
	name: string;
	unit: string;
	rate: number;
};

type ConfirmationProps = {
	date: string;
	positions: Record<string, ConfirmationPosition>;
	before: Record<string, number | null>;
	after: Record<string, number | null>;
	crewBefore: number;
	crewAfter: number;
	amountBefore: number;
	amountAfter: number;
	connected: boolean;
	exceeds: boolean;
	renderMoney: (value: number) => ReactNode;
	workContent?: ReactNode;
	crewContent?: ReactNode;
	workSummary?: string;
};

export function ReportConfirmation(props: ConfirmationProps) {
	const { before, after, positions, renderMoney } = props;
	const identifiers = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
		(id) => before[id] !== after[id],
	);
	const numberFormat = new Intl.NumberFormat('ru-BY', {
		maximumFractionDigits: 2,
	});
	const perPersonBefore = Math.floor((props.amountBefore * 100) / props.crewBefore) / 100;
	const perPersonAfter = Math.floor((props.amountAfter * 100) / props.crewAfter) / 100;
	return (
		<div className="confirmation-detail">
			<div className="confirmation-date">
				{dayjs(props.date).format('D MMMM YYYY')}
				<span>{props.workSummary || `${identifiers.length} изменений в работах`}</span>
			</div>
			{props.workContent ?? (
				<div className="confirmation-work-list">
					{identifiers.map((id) => {
						const position = positions[id];
						if (!position) return null;
						const previous = before[id] || 0;
						const next = after[id] || 0;
						const state = !previous ? 'added' : !next ? 'removed' : 'edited';
						return (
							<div className={'confirmation-work ' + state} key={id}>
								<div className="confirmation-work-title">
									<span className="confirmation-work-icon">
										{state === 'added' ? (
											<Plus size={15} />
										) : state === 'removed' ? (
											<Minus size={15} />
										) : (
											<ArrowRight size={15} />
										)}
									</span>
									<b>{position.name}</b>
									<span className="confirmation-change-label">
										{state === 'added' ? 'Добавлено' : state === 'removed' ? 'Убрано' : 'Изменено'}
									</span>
								</div>
								<div className="confirmation-values">
									<span>Объём</span>
									<del>
										{numberFormat.format(previous)} {position.unit}
									</del>
									<ArrowRight size={13} />
									<strong>
										{numberFormat.format(next)} {position.unit}
									</strong>
								</div>
								<div className="confirmation-values amount-values">
									<span>Сумма</span>
									<del>{renderMoney(previous * position.rate)}</del>
									<ArrowRight size={13} />
									<strong>{renderMoney(next * position.rate)}</strong>
								</div>
							</div>
						);
					})}
				</div>
			)}
			{props.crewContent !== undefined
				? props.crewContent
				: props.crewBefore !== props.crewAfter && (
						<div className="confirmation-crew">
							<span>
								<Users size={15} />
								Работников
							</span>
							<div>
								<del>{props.crewBefore}</del>
								<ArrowRight size={14} />
								<strong>{props.crewAfter} чел.</strong>
							</div>
						</div>
					)}
			<div className="confirmation-total">
				<div className="confirmation-total-heading">
					<span>Выработка за день</span>
					<small>Белорусские рубли</small>
				</div>
				<div className="confirmation-total-amount">
					<del>{renderMoney(props.amountBefore)}</del>
					<ArrowRight size={18} />
					<strong>{renderMoney(props.amountAfter)}</strong>
				</div>
				<div className="confirmation-person">
					<span>На одного человека</span>
					<div>
						<del>{renderMoney(perPersonBefore)}</del>
						<ArrowRight size={13} />
						<strong>{renderMoney(perPersonAfter)}</strong>
					</div>
				</div>
			</div>
			{props.exceeds && (
				<Alert
					showIcon
					type="warning"
					message="Объём превышает остаток по смете. Подтвердите фактически выполненные работы."
				/>
			)}
			{!props.connected && (
				<div className="confirmation-delivery not-connected">
					<CloudUpload size={18} />
					<span>Отчёт сохранится в приложении.</span>
				</div>
			)}
		</div>
	);
}
