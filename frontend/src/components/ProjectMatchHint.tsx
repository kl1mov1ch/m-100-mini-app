import type { ProjectMatch } from '../types';
import { Button } from './Button';
import './project-match-hint.css';

export function ProjectMatchHint({
	match,
	onSwitch,
	onDismiss,
}: {
	match: ProjectMatch;
	onSwitch: (id: string) => void;
	onDismiss: () => void;
}) {
	return (
		<aside className="project-match-hint">
			<p>
				Похоже, работа «{match.work_name}» есть в объекте <strong>{match.project_name}</strong>.
			</p>
			<div>
				<Button size="small" onClick={() => onSwitch(match.project_id)}>
					Переключиться
				</Button>
				<Button size="small" type="text" onClick={onDismiss}>
					Остаться
				</Button>
			</div>
		</aside>
	);
}
