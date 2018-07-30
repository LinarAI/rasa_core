
# from rasa_core.trackers import DialogueStateTracker
# from rasa_core.domain import Domain
import numpy as np
from rasa_core.actions import Action
from rasa_core.events import Event, SlotSet
import logging


logger = logging.getLogger(__name__)



class Plan(object):
    """Next action to be taken in response to a dialogue state."""

    def next_action_idx(self, tracker, domain):
        # type: (DialogueStateTracker, Domain) -> List[Event]
        """
        Choose an action idx given the current state of the tracker and the plan.

        Args:
            tracker (DialogueStateTracker): the state tracker for the current user.
                You can access slot values using ``tracker.get_slot(slot_name)``
                and the most recent user message is ``tracker.latest_message.text``.
            domain (Domain): the bot's domain

        Returns:
            idx: the index of the next planned action in the domain

        """

        raise NotImplementedError

    def __str__(self):
        return "Plan('{}')".format(self.name)


class SimpleForm(Plan):
    def __init__(self, name, slot_dict, finish_action, optional_slots=None, exit_dict=None, chitchat_dict=None, details_intent=None, rules=None, subject=None):
        self.name = name
        self.slot_dict = slot_dict
        self.current_required = list(self.slot_dict.keys())
        self.required_slots = self.current_required
        self.optional_slots = optional_slots
        # exit dict is {exit_intent_name: exit_action_name}
        self.exit_dict = exit_dict
        self.chitchat_dict = chitchat_dict
        self.finish_action = finish_action
        self.details_intent = details_intent
        self.rules_yaml = rules
        self.rules = self._process_rules(self.rules_yaml)
        self.subject = subject

        self.last_question = None
        self.queue = []

    def _process_rules(self, rules):
        rule_dict = {}
        for slot, values in rules.items():
            for value, rules in values.items():
                rule_dict[(slot, value)] = (rules.get('need'), rules.get('lose'))
        return rule_dict

    def _update_requirements(self, tracker):
        #type: (DialogueStateTracker)
        if self.rules is None:
            return
        all_add, all_take = [], []
        for slot_tuple in list(tracker.current_slot_values().items()):
            if slot_tuple in self.rules.keys():
                add, take = self.rules[slot_tuple]
                if add is not None:
                    all_add.extend(add)
                if take is not None:
                    all_take.extend(take)
        self.current_required = list(set(self.required_slots+all_add)-set(all_take))

    def check_unfilled_slots(self, tracker):
        current_filled_slots = [key for key, value in tracker.current_slot_values().items() if value is not None]
        still_to_ask = list(set(self.current_required) - set(current_filled_slots))
        return still_to_ask

    def _run_through_queue(self, domain):
        if self.queue == []:
            return None
        else:
            return domain.index_for_action(self.queue.pop(0))

    def _make_question_queue(self, question):
        queue = [self.slot_dict[question]['ask_utt'], 'action_listen']
        if 'follow_up_action' in self.slot_dict[self.last_question].keys():
            queue.append(self.slot_dict[self.last_question]['follow_up_action'])
        return queue


    def next_action_idx(self, tracker, domain):
        # type: (DialogueStateTracker, Domain) -> int

        out = self._run_through_queue(domain)
        if out is not None:
            return out

        intent = tracker.latest_message.parse_data['intent']['name'].replace('plan_', '', 1)
        self._update_requirements(tracker)

        # for v0.1 lets assume that the entities are same as slots so they are already set
        if intent in self.exit_dict.keys():
            # actions in this dict should deactivate this plan in the tracker
            self.queue = [self.exit_dict[intent]]
            return self._run_through_queue(domain)
        elif intent in self.chitchat_dict.keys() and tracker.latest_action_name not in self.chitchat_dict.values():
            self.queue = [self.chitchat_dict[intent]]
            self.queue.append(self._make_question_queue(self.last_question))
            return self._run_through_queue(domain)
        elif intent in self.details_intent and 'utter_explain' not in tracker.latest_action_name:
            self.queue = [self.slot_dict[self.last_question]['clarify_utt']]
            self.queue.append(self._make_question_queue(self.last_question))
            return self._run_through_queue(domain)

        still_to_ask = self.check_unfilled_slots(tracker)

        if len(still_to_ask) == 0:
            self.queue = [self.finish_action, 'action_listen']
            return self._run_through_queue(domain)
        else:
            self.last_question = np.random.choice(still_to_ask)
            self.queue = self._make_question_queue(self.last_question)
            return self._run_through_queue(domain)

    def as_dict(self):
        return {"name": self.name,
                "required_slots": self.slot_dict,
                "optional_slots": self.optional_slots,
                "finish_action": self.finish_action,
                "exit_dict": self.exit_dict,
                "chitchat_dict": self.chitchat_dict,
                "details_intent": self.details_intent,
                "rules": self.rules_yaml,
                "subject": self.subject}


class ActivatePlan(Action):
    def __init__(self):
        self._name = 'activate_plan'

    def run(self, dispatcher, tracker, domain):
        """Simple run implementation uttering a (hopefully defined) template."""
        # tracker.activate_plan(domain)
        return [StartPlan(domain), SlotSet('active_plan', True)]

    def name(self):
        return self._name

    def __str__(self):
        return "ActivatePlan('{}')".format(self.name())


class PlanComplete(Action):
    def __init__(self):
        self._name = 'deactivate_plan'

    def run(self, dispatcher, tracker, domain):
        unfilled = tracker.active_plan.check_unfilled_slots(tracker)
        if len(unfilled) == 0:
            complete = True
        else:
            complete = False
        return [EndPlan(), SlotSet('active_plan', False), SlotSet('plan_complete', complete)]

    def name(self):
        return self._name

    def __str__(self):
        return "PlanComplete('{}')".format(self.name())


class StartPlan(Event):
    def __init__(self, domain, plan_name):
        super(StartPlan).__init__()
        self.plan = domain._plans.get(plan_name, [])
        if self.plan == []:
            logger.error("Tried to set non existent plan '{}'. Make sure you "
                         "added all your plans to your domain file."
                         "".format(plan_name))

    def apply_to(self, tracker):
        # type: (DialogueStateTracker) -> None
        tracker.activate_plan(self.plan)

    def as_story_string(self):
        return None


class EndPlan(Event):
    def apply_to(self, tracker):
        tracker.deactivate_plan()

    def as_story_string(self):
        return None