import sys

from rlbot.managers import Bot
from rlbot_flatbuffers import GamePacket, ControllerState, MatchPhase

from controllers import other
from behaviours.carry import Carry
from behaviours.clear_ball import ClearBall
from behaviours.save_goal import SaveGoal
from behaviours.shoot_at_goal import ShootAtGoal
from controllers.fly import FlyController
from maneuvers.kickoff import choose_kickoff_maneuver
from utility.info import GameInfo
from controllers.drive import DriveController
from controllers.shooting import ShotController
from controllers.aim_cone import AimCone
from utility.rendering import draw_ball_path
from behaviours.utsystem import UtilitySystem, Choice
from utility.vec import xy, Vec3, norm, dot, euler_to_rotation

RENDER = True


class Beast(Bot):
    def __init__(self):
        super().__init__("eastvillage/beast/2.3.0")

        self.do_rendering = RENDER
        self.info = None
        self.choice = None
        self.maneuver = None
        self.doing_kickoff = False

        self.ut = None
        self.drive = DriveController()
        self.shoot = ShotController()
        self.fly = FlyController()

        self.initialized = False

    def initialize(self):
        self.info = GameInfo(self.index, self.team)
        self.ut = UtilitySystem([DefaultBehaviour(), ShootAtGoal(), ClearBall(self), SaveGoal(self), Carry()])
        self.print("Initialized!")

    def get_output(self, packet: GamePacket) -> ControllerState:

        # Read packet
        if not self.info.field_info_loaded:
            self.info.read_field_info(self.field_info)
            if not self.info.field_info_loaded:
                return ControllerState()
        if len(packet.balls) == 0 or self.ball_prediction is None:
            return ControllerState()
        self.info.read_packet(packet)

        # Check if match is over
        if packet.match_info.match_phase == MatchPhase.Ended:
            return other.celebrate(self)  # Assuming we win!

        self.renderer.begin_rendering()

        controller = self.use_brain()

        # Additional rendering
        if self.do_rendering:
            draw_ball_path(self, 4, 5)
            doing = self.maneuver or self.choice
            if doing is not None:
                status_str = f'{self.name}: {doing.__class__.__name__}'
                self.renderer.draw_string_2d(status_str, 0.03, 0.3 + self.index * 22/1080, 1, self.renderer.team_color(self.team, True))

        self.renderer.end_rendering()

        # Save some stuff for next tick
        self.feedback(controller)

        return controller

    def print(self, s):
        print(f"Beast i{self.index} t{self.team} :", s)

    def feedback(self, controller):
        if controller is None:
            self.print(f"None controller from state: {self.choice.__class__} & {self.maneuver.__class__}")
        else:
            self.info.my_car.last_input.roll = controller.roll
            self.info.my_car.last_input.pitch = controller.pitch
            self.info.my_car.last_input.yaw = controller.yaw
            self.info.my_car.last_input.boost = controller.boost

    def use_brain(self) -> ControllerState:
        # Check kickoff
        if self.info.is_kickoff and not self.doing_kickoff:
            self.maneuver = choose_kickoff_maneuver(self)
            self.doing_kickoff = True
            #self.print("Kickoff")

        # Execute logic
        if self.maneuver is None or self.maneuver.done:
            # There is no maneuver, use utility system to find a choice
            self.maneuver = None
            self.doing_kickoff = False
            self.choice = self.ut.evaluate(self)
            ctrl = self.choice.exec(self)
            # The choice has started a maneuver, reset utility system and execute maneuver instead
            if self.maneuver is not None:
                self.ut.reset()
                self.choice = None
                return self.maneuver.exec(self)
            return ctrl

        return self.maneuver.exec(self)


class DefaultBehaviour(Choice):
    def __init__(self):
        pass

    def utility(self, bot):
        return 0.1

    def exec(self, bot):

        car = bot.info.my_car
        ball = bot.info.ball

        car_to_ball = ball.pos - car.pos
        ball_to_enemy_goal = bot.info.enemy_goal - ball.pos
        own_goal_to_ball = ball.pos - bot.info.own_goal
        dist = norm(car_to_ball)

        offence = ball.pos.y * bot.info.team_sign < 0
        dot_enemy = dot(car_to_ball, ball_to_enemy_goal)
        dot_own = dot(car_to_ball, own_goal_to_ball)
        right_side_of_ball = dot_enemy > 0 if offence else dot_own > 0

        if right_side_of_ball:
            # Aim cone
            dir_to_post_1 = (bot.info.enemy_goal + Vec3(3800, 0, 0)) - bot.info.ball.pos
            dir_to_post_2 = (bot.info.enemy_goal + Vec3(-3800, 0, 0)) - bot.info.ball.pos
            cone = AimCone(dir_to_post_1, dir_to_post_2)
            cone.get_goto_point(bot, car.pos, bot.info.ball.pos)
            if bot.do_rendering:
                cone.draw(bot, bot.info.ball.pos)

            # Chase ball
            return bot.drive.go_towards_point(bot, xy(ball.pos), 2000, True, True, can_dodge=dist > 2200)
        else:
            # Go home
            return bot.drive.go_towards_point(bot, bot.info.own_goal_field, 2000, True, True)


if __name__ == '__main__':
    Beast().run()
