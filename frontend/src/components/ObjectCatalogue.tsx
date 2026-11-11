import { Alert, Button, Empty, Input, Spin, Tag } from 'antd';
import { ChevronRight, Eye, EyeOff, Search, Trash2, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { Money, nf, unit } from '../lib/format';
import type { ObjectManagement, Position } from '../types';
import { BitrixReadStatus } from './BitrixReadStatus';
import { positionOverrun } from './PositionDetails';

export function ObjectCatalogue({
	workspace,
	management,
	error,
	onManage,
	onView,
}: {
	workspace: WorkspaceView;
	management: ObjectManagement | null;
	error: string;
	onManage: (position: Position) => void;
	onView: (position: Position) => void;
}) {
	const [query, setQuery] = useState('');
	const { allPositions, positions, byId, openObjectSection } = workspace;
	const term = query.trim().toLocaleLowerCase('ru');
	const matching = allPositions
		.filter((position) =>
			[position.name, position.section, position.source_sheet]
				.filter(Boolean)
				.join(' ')
				.toLocaleLowerCase('ru')
				.includes(term),
		)
		.sort((left, right) => Number(positionOverrun(left) > 0) - Number(positionOverrun(right) > 0));
	if (!allPositions.length) {
		return (
			<section className="object-panel">
				<Empty description="Смета пуста" image={Empty.PRESENTED_IMAGE_SIMPLE} />
				<Button type="primary" onClick={() => openObjectSection('table')}>
					Добавить таблицу
				</Button>
			</section>
		);
	}
	return (
		<section className="object-panel">
			<div className="object-panel-heading">
				<h2>Смета</h2>
				<Tag>
					{positions.length} из {allPositions.length} в подборе
				</Tag>
			</div>
			<BitrixReadStatus workspace={workspace} />
			<Input
				aria-label="Найти работу в смете"
				placeholder="Название работы"
				prefix={<Search size={17} />}
				allowClear
				value={query}
				onChange={(event) => setQuery(event.target.value)}
			/>
			{error && <Alert type="warning" showIcon message={error} />}
			{!management && !error && <Spin size="small" />}
			{!matching.length && (
				<Empty description="Работы не найдены" image={Empty.PRESENTED_IMAGE_SIMPLE} />
			)}
			<ul className="object-catalogue">
				{matching.map((position) => {
					const used = management?.used_positions.includes(position.id);
					const overrun = positionOverrun(position);
					const linked = position.linked_work_id ? byId[position.linked_work_id] : null;
					const label = position.hidden
						? 'Вернуть в подбор'
						: overrun > 0
							? 'Скрыть из подбора'
							: 'Удалить из сметы';
					const Icon = position.hidden ? Eye : overrun > 0 ? EyeOff : Trash2;
					return (
						<li key={position.id} className={overrun > 0 ? 'catalogue-overrun' : undefined}>
							<button type="button" className="catalogue-position" onClick={() => onView(position)}>
								<b>{position.name}</b>
								<small>
									План {nf.format(position.planned)} · Выполнено {nf.format(position.completed)} ·
									Остаток {nf.format(position.remaining)} {unit(position.unit)}
								</small>
								<small>
									<Money value={position.rate} /> / {unit(position.unit)}
								</small>
								{linked && <small>Работа: {linked.name}</small>}
								{overrun > 0 && (
									<span className="catalogue-overrun-label">
										<TriangleAlert size={14} /> Перерасход {nf.format(overrun)}{' '}
										{unit(position.unit)}
									</span>
								)}
								{position.hidden && <Tag color="gold">Скрыта из подбора</Tag>}
								<ChevronRight className="catalogue-position-arrow" size={17} />
							</button>
							{management && (position.hidden || overrun > 0 || !used) && (
								<Button
									size="small"
									danger={!position.hidden && !overrun}
									aria-label={label + ' — ' + position.name}
									title={label}
									icon={<Icon size={17} />}
									onClick={() => onManage(position)}
								/>
							)}
						</li>
					);
				})}
			</ul>
			{positions.length > 0 && !workspace.active?.work_dates?.length && (
				<Button type="primary" onClick={() => openObjectSection('reports')}>
					Заполнить первый отчёт
				</Button>
			)}
		</section>
	);
}
