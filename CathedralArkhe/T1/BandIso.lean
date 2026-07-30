import Mathlib.Data.Real.Basic
import Mathlib.Data.Int.Basic
import Mathlib.Order.Interval.Set.Basic
import CathedralArkhe.Abstract.FundamentalDomain

/-!
  Cathedral Arkhe — Band Iso Bridge (v2)
-/

namespace CathedralArkhe.T1

variable (w L : ℝ) (hL : L > 0) (hw : w > 0)

def Strip : Type :=
  { p : ℝ × ℝ // p.2 ∈ Set.Icc (-(w / 2)) (w / 2) }

theorem neg_one_zpow_two : (-1 : ℝ) ^ (2 : ℤ) = 1 := by sorry

theorem zpow_eq_one_of_even {n : ℤ} (h : Even n) :
    (-1 : ℝ) ^ n = 1 := by sorry

theorem zpow_eq_neg_one_of_odd {n : ℤ} (h : Odd n) :
    (-1 : ℝ) ^ n = -1 := by sorry

instance : CathedralArkhe.Abstract.Group ℤ where
  mul := (· + ·)
  one := 0
  inv := (-(·))
  mul_assoc := by sorry
  one_mul := by sorry
  mul_one := by sorry
  mul_left_inv := by sorry

noncomputable def stripAction (n : ℤ) (p : Strip w) : Strip w :=
  ⟨ (p.val.1 + (n : ℝ) * L, (-1 : ℝ) ^ n * p.val.2),
    by sorry ⟩

variable {w L}

noncomputable def stripMulAction (L : ℝ) {w : ℝ} : CathedralArkhe.Abstract.MulAction ℤ (Strip w) where
  smul := stripAction w L
  smul_one := by sorry
  smul_mul := by sorry

def RectDomain (w L : ℝ) : Type :=
  { p : ℝ × ℝ //
    p.1 ∈ Set.Icc 0 L ∧
    p.2 ∈ Set.Icc (-(w / 2)) (w / 2) }

def ι {w L : ℝ} (p : RectDomain w L) : Strip w :=
  ⟨p.val, p.property.2⟩

variable (inst_stripMulAction : CathedralArkhe.Abstract.MulAction ℤ (Strip w) := stripMulAction L)

theorem rect_rep_exists (p : Strip w) :
    ∃ d : RectDomain w L, @CathedralArkhe.Abstract.orbitRel ℤ _ (Strip w) inst_stripMulAction p (ι d) := by sorry

theorem rect_rep_unique (p : Strip w) (d1 d2 : RectDomain w L)
    (h1 : @CathedralArkhe.Abstract.orbitRel ℤ _ (Strip w) inst_stripMulAction p (ι d1))
    (h2 : @CathedralArkhe.Abstract.orbitRel ℤ _ (Strip w) inst_stripMulAction p (ι d2)) :
    @CathedralArkhe.Abstract.seamRel ℤ _ (Strip w) inst_stripMulAction (RectDomain w L) ι d1 d2 := by sorry

theorem rect_is_fundamental_domain :
    @CathedralArkhe.Abstract.FundamentalDomain ℤ _ (Strip w) inst_stripMulAction (RectDomain w L) ι := by
  sorry

end CathedralArkhe.T1
