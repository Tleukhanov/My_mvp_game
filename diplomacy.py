from typing import Dict, Tuple, Optional
from world_data import Relation, WORLD_NATIONS


class DiplomacyManager:
    def __init__(self):
        self._relations: Dict[Tuple[str, str], Relation] = {}
        self._init_relations()

    def _init_relations(self):
        nations = list(WORLD_NATIONS.keys())
        for i, n1 in enumerate(nations):
            for n2 in nations[i + 1:]:
                if n1 == "red" and n2 == "blue":
                    self._relations[(n1, n2)] = Relation.WAR
                    self._relations[(n2, n1)] = Relation.WAR
                elif n1 == "red" and n2 == "green":
                    self._relations[(n1, n2)] = Relation.NEUTRAL
                    self._relations[(n2, n1)] = Relation.NEUTRAL
                elif n1 == "blue" and n2 == "green":
                    self._relations[(n1, n2)] = Relation.FRIENDLY
                    self._relations[(n2, n1)] = Relation.FRIENDLY

    def get_relation(self, nation_a: str, nation_b: str) -> Relation:
        if nation_a == nation_b:
            return Relation.ALLIANCE
        return self._relations.get((nation_a, nation_b), Relation.NEUTRAL)

    def set_relation(self, nation_a: str, nation_b: str, relation: Relation):
        self._relations[(nation_a, nation_b)] = relation
        self._relations[(nation_b, nation_a)] = relation

    def can_move_through(self, mover: str, owner: str) -> bool:
        rel = self.get_relation(mover, owner)
        return rel in (Relation.ALLIANCE, Relation.FRIENDLY)

    def is_enemy(self, nation_a: str, nation_b: str) -> bool:
        return self.get_relation(nation_a, nation_b) == Relation.WAR

    def propose(self, proposer: str, target: str,
                proposal: Relation) -> Tuple[bool, str]:
        current = self.get_relation(proposer, target)

        if proposal == current:
            return False, "Уже в таких отношениях"

        if proposal == Relation.WAR:
            self.set_relation(proposer, target, Relation.WAR)
            return True, f"{WORLD_NATIONS[proposer].name} объявила войну {WORLD_NATIONS[target].name}!"

        if proposal == Relation.ALLIANCE:
            if current == Relation.FRIENDLY:
                self.set_relation(proposer, target, Relation.ALLIANCE)
                return True, f"{WORLD_NATIONS[target].name} приняла альянс!"
            else:
                return False, f"{WORLD_NATIONS[target].name} не дружна с вами. Сначала подружитесь."

        if proposal == Relation.FRIENDLY:
            if current == Relation.NEUTRAL:
                if self._accept_friendship(target, proposer):
                    self.set_relation(proposer, target, Relation.FRIENDLY)
                    return True, f"{WORLD_NATIONS[target].name} приняла дружбу!"
                else:
                    return False, f"{WORLD_NATIONS[target].name} отклонила предложение дружбы."
            elif current == Relation.WAR:
                return False, "Нельзя подружиться во время войны."
            else:
                return False, "Уже дружите или в альянсе."

        if proposal == Relation.NEUTRAL:
            if current == Relation.WAR:
                if self._acceptPeace(target, proposer):
                    self.set_relation(proposer, target, Relation.NEUTRAL)
                    return True, f"{WORLD_NATIONS[target].name} согласна на мир!"
                else:
                    return False, f"{WORLD_NATIONS[target].name} отклонила мир."
            elif current == Relation.ALLIANCE:
                self.set_relation(proposer, target, Relation.FRIENDLY)
                return True, "Альянс расторгнут, теперь дружба."
            elif current == Relation.FRIENDLY:
                self.set_relation(proposer, target, Relation.NEUTRAL)
                return True, "Дружба прекращена."

        return False, "Невозможно"

    def _accept_friendship(self, target: str, proposer: str) -> bool:
        import random
        return random.random() < 0.6

    def _acceptPeace(self, target: str, proposer: str) -> bool:
        import random
        return random.random() < 0.4

    def get_relation_name(self, nation_a: str, nation_b: str) -> str:
        rel = self.get_relation(nation_a, nation_b)
        names = {
            Relation.WAR: "ВОЙНА",
            Relation.NEUTRAL: "НЕЙТРАЛИТЕТ",
            Relation.FRIENDLY: "ДРУЖБА",
            Relation.ALLIANCE: "АЛЬЯНС",
        }
        return names.get(rel, "???")

    def get_relation_color(self, nation_a: str, nation_b: str) -> Tuple[int, int, int]:
        rel = self.get_relation(nation_a, nation_b)
        colors = {
            Relation.WAR: (200, 60, 60),
            Relation.NEUTRAL: (180, 170, 150),
            Relation.FRIENDLY: (80, 180, 80),
            Relation.ALLIANCE: (60, 120, 220),
        }
        return colors.get(rel, (180, 170, 150))
