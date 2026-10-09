import unittest
from autoresearch_flow.common import FlowError
from autoresearch_flow.runtime_rpc import GoalSession


class FakeRpc:
    def __init__(self, status='paused', thread_status='idle'):
        self.calls = []
        self.thread_status=thread_status
        self.goal = {'threadId': 'original', 'objective': 'original objective', 'status': status,
                     'tokensUsed': 17, 'timeUsedSeconds': 23}

    def request(self, method, params):
        self.calls.append((method, params.copy()))
        if method in {'thread/start', 'thread/resume'}:
            return {'thread': {'id': 'original'}}
        if method=='thread/read':
            return {'thread':{'id':'original','status':{'type':self.thread_status}}}
        if method == 'thread/goal/set':
            self.goal.update(params)
        if method.startswith('thread/goal/'):
            return {'goal': self.goal.copy()}
        return {'turn': {'id': 'turn1'}}


class GoalRecoveryTests(unittest.TestCase):
    def test_resume_original_goal_without_resetting_objective_or_counters(self):
        rpc = FakeRpc()
        session = GoalSession(rpc, model='configured', thread_id='original')
        result = session.resume('original objective', '继续原会话')
        self.assertEqual(result['status'], 'active')
        self.assertEqual(result['tokensUsed'], 17)
        updates = [params for method, params in rpc.calls if method == 'thread/goal/set']
        self.assertEqual(updates, [{'threadId': 'original', 'status': 'active'}])
        self.assertEqual(rpc.calls[0][1]['threadId'], 'original')

    def test_active_goal_is_not_recreated(self):
        rpc = FakeRpc('active')
        GoalSession(rpc, model='configured', thread_id='original').resume('original objective', '继续')
        self.assertFalse(any(method == 'thread/goal/set' for method, _ in rpc.calls))

    def test_reconnect_active_turn_does_not_inject_duplicate_turn(self):
        rpc=FakeRpc('active',thread_status='active')
        GoalSession(rpc,model='configured',thread_id='original').resume('original objective','继续')
        self.assertFalse(any(method=='turn/start' for method,_ in rpc.calls))
        rpc=FakeRpc('active',thread_status='systemError')
        with self.assertRaises(FlowError):
            GoalSession(rpc,model='configured',thread_id='original').resume('original objective','继续')

    def test_blocked_limited_complete_or_changed_goal_not_silently_replaced(self):
        for status in ['blocked', 'usageLimited', 'budgetLimited', 'complete']:
            rpc = FakeRpc(status)
            with self.assertRaises(FlowError):
                GoalSession(rpc, model='configured', thread_id='original').resume('original objective', '继续')
            self.assertFalse(any(method == 'thread/goal/set' for method, _ in rpc.calls))
        rpc = FakeRpc()
        with self.assertRaises(FlowError):
            GoalSession(rpc, model='configured', thread_id='original').resume('different objective', '继续')

    def test_start_sets_goal_once_and_no_wall_clock_or_token_budget(self):
        rpc = FakeRpc('active')
        goal = GoalSession(rpc, model='configured').start('original objective', '独立迭代')
        updates = [p for m, p in rpc.calls if m == 'thread/goal/set']
        self.assertEqual(len(updates), 1)
        self.assertNotIn('tokenBudget', updates[0])
        self.assertNotIn('wallClock', updates[0])
        self.assertEqual(goal['status'], 'active')


if __name__ == '__main__':
    unittest.main()
