import unrealsdk # type: ignore
from Mods import ModMenu # type: ignore
from collections import namedtuple

class CleaningUpPandora(ModMenu.SDKMod):
    Name: str = "Cleaning Up Pandora"
    Author: str = "Deceptix_"
    Description: str = ("Adds the ability to sell items that are on the floor or in your backpack by pressing the 'Secondary Use' key.\n\n"
                        "NOTE:\n<ul><li>Items that are favorited or equipped cannot be sold.</li>"
                        "<li>Controller users need to press 'Start' to sell items from their backpack</li>"
                        "<li>All sold items can be bought back from any vendor.</ul>")
    Version: str = "1.0.0"
    SupportedGames: ModMenu.Game = ModMenu.Game.BL2 | ModMenu.Game.TPS
    Types: ModMenu.ModTypes = ModMenu.ModTypes.Utility
    SaveEnabledState: ModMenu.EnabledSaveType = ModMenu.EnabledSaveType.LoadWithSettings

    sellAudio = None
    canSwap = True

    @ModMenu.Hook("WillowGame.WillowPlayerController.SawPickupable")
    def InitializeFromDefinition(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        base_icon = unrealsdk.FindObject("InteractionIconDefinition", "GD_InteractionIcons.Default.Icon_DefaultUse")
        icon = unrealsdk.ConstructObject(
                    Class=base_icon.Class,
                    Outer=base_icon.Outer,
                    Name="SecondaryUse",
                    Template=base_icon,
                )
        unrealsdk.KeepAlive(icon)
        icon.Icon = 4

        caller.ServerRCon(f"set {caller.PathName(icon)} Action UseSecondary")
        caller.ServerRCon(f"set {caller.PathName(icon)} Text SELL ITEM")
        
        # Instead of using the Structs mod, we create the tuple ourselves to use in place of the structure
        InteractionIconWithOverrides = namedtuple('InteractionIconWithOverrides',
                                                  ['IconDef', 'OverrideIconDef', 'bOverrideIcon', 'bOverrideAction', 'bOverrideText', 'bCostsToUse', 'CostsCurrencyType', 'CostsAmount'],
                                                  defaults=[None, None, False, False, False, 0, 0, 0])
        
        seenItemType = params.Pickup.ObjectPointer.GetPickupableInventory().Class.Name
        if seenItemType != "WillowUsableItem" and seenItemType != "WillowMissionItem": # Checks the type of item the player is looking at to make sure its something sellable
            hudMovie = caller.GetHUDMovie()
            if hudMovie == None: # This fixes an error that is caused when looking at a pickupable directly after closing the inventory
                return True
            hudMovie.ShowToolTip(InteractionIconWithOverrides(IconDef = icon), 1) # Show the tooltip in the hud
            if caller.PlayerInput.bUsingGamepad is True:
                self.canSwap = False # Because the Secondary Use Key on controller is the same as swap weapons, we need to restrict the ability to swap when looking at a pickupable object
        return True

    @ModMenu.Hook("WillowGame.StatusMenuInventoryPanelGFxObject.SetTooltipText")
    def setTooltipText(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        WPC = unrealsdk.GetEngine().GamePlayers[0].Actor
        secondaryUseKey = WPC.PlayerInput.GetKeyForAction("UseSecondary")

        if caller.bInEquippedView is True: # Only show updated tooltip when looking at the backpack as you cannot delete items that are equipped
            return True

        if WPC.PlayerInput.bUsingGamepad is False:
            result: str = ""
            result = f"{params.TooltipsText}\n[{secondaryUseKey}] Sell Item" # Connects the normal tooltip text with our custom text

        if WPC.PlayerInput.bUsingGamepad is True:
                secondaryUseKey = "<IMG src='xbox360_Start' vspace='-3'>" # Adds the correct controller input image to the tooltip
                result: str = ""
                result = f"{params.TooltipsText}\n{secondaryUseKey} Sell Item" # Connects the normal tooltip text with our custom text

        caller.SetTooltipText(result)
        return False

    @ModMenu.Hook("WillowGame.WillowPlayerController.PerformedSecondaryUseAction")
    def onUse(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        inventoryManager = caller.GetPawnInventoryManager()
        backpack = inventoryManager.Backpack

        seenItem = caller.CurrentSeenPickupable.ObjectPointer
        if seenItem == None: # If the player is looking at nothing, we do nothing
            return True
        seenItemType = seenItem.GetPickupableInventory().Class.Name
        
        if seenItemType != "WillowUsableItem" and seenItemType != "WillowMissionItem": # Checks the type of item the player is looking at to make sure its something sellable
            if seenItem.bPickupable == True and seenItem.bIsMissionItem == False:
                seenItem.GetPickupableInventory().Mark = 0
                seenItem.SetPickupability(False) # Turn off the ability for the player to pick up the item
                seenItem.PickupShrinkDuration = 0.5
                seenItem.BeginShrinking() # Deletes the gun
                for item in backpack: # In case other items in the backpack are marked as trash, we remove the mark in order to not accidentally sell the item
                    if item is None:
                        continue
                    if item.GetMark() == 0: # PlayerMark.PM_Trash
                        item.Mark = 1 # PlayerMark.PM_Standard
                inventoryManager.AddBackpackInventory(seenItem.GetPickupableInventory()) # Adds the weapon on the floor straight to our inventory to sell
                inventoryManager.SellAllTrash()
                self.playSound() # Plays the vendor sell sound
                self.buybackInventoryUnmark() # Marks sold items as standard
        return True
    
    @ModMenu.Hook("WillowGame.StatusMenuInventoryPanelGFxObject.NormalInputKey")
    def onUseBackpack(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        WPC = unrealsdk.GetEngine().GamePlayers[0].Actor
        inventoryManager = WPC.GetPawnInventoryManager()
        backpack = inventoryManager.Backpack

        if WPC.PlayerInput.bUsingGamepad is False:
            if params.ukey != WPC.PlayerInput.GetKeyForAction("UseSecondary"): # Looks for Secondary Use Key
                return True
        if WPC.PlayerInput.bUsingGamepad is True:
            if "Start" not in str(params.ukey): # Looks for Start button
                return True
        if params.Uevent == 0: # Checks if pressed
            selectedItem = caller.GetSelectedThing() # Gets Willow Definition of selected item in inventory
            if selectedItem is None or caller.bInEquippedView is True or selectedItem.GetMark() == 2:
                caller.ParentMovie.PlayUISound('ResultFailure') # Plays an error sound if player tries to sell an item that is either equipped or favorited
                return True
            for item in backpack: # in case other items in the backpack are marked as trash, we remove the mark in order to not accidentally sell the item
                if item.GetMark() == 0: # PlayerMark.PM_Trash
                    item.Mark = 1 # PlayerMark.PM_Standard
            selectedItem.Mark = 0 # PlayerMark.PM_Trash
            inventoryManager.SellAllTrash()
            caller.FlourishEquip("SOLD") # Displays a confirmation message
            self.playSound() # Plays the vendor sell sound
            self.buybackInventoryUnmark() # Marks sold items as standard
        return True
    
    @ModMenu.Hook("WillowGame.StatusMenuExGFxMovie.InventoryPanelInputKey")
    def onUseBackpackRefresh(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        WPC = unrealsdk.GetEngine().GamePlayers[0].Actor

        if WPC.PlayerInput.bUsingGamepad is False:
            if params.ukey != WPC.PlayerInput.GetKeyForAction("UseSecondary"): # Looks for Secondary Use Key
                return True
        if WPC.PlayerInput.bUsingGamepad is True:
            if "Start" not in str(params.ukey): # Looks for Start button
                return True
        if params.Uevent == 0: # Checks if pressed
            caller.InventoryRefreshRate = 0.01 # Lowers inventory refresh rate timer
            caller.SetInventoryRefreshTimer() # Refreshes the inventory after the timer is over
            caller.InventoryRefreshRate = 0.5 # Resets the inventory refresh rate in case this hurts something else
        return True
    
    @ModMenu.Hook("WillowGame.WillowPlayerController.ClearSeenPickupable")
    def noPickup(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        self.canSwap = True # Allows the player to swap weapons after looking away from a pickupable
        return True
    
    @ModMenu.Hook("WillowGame.WillowPlayerController.NextWeapon")
    def onSwap(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        return self.canSwap

    def playSound(self) -> None:
        # Took the sell audio search from apple1417's "AltUseVendors" (https://bl-sdk.github.io/mods/AltUseVendors/)
        WPC = unrealsdk.GetEngine().GamePlayers[0].Actor
        if self.sellAudio is None:
            self.sellAudio = unrealsdk.FindObject("AkEvent", 'Ake_UI.UI_Vending.Ak_Play_UI_Vending_Sell')
        unrealsdk.KeepAlive(self.sellAudio)
        WPC.Pawn.PlayAkEvent(self.sellAudio)

    def buybackInventoryUnmark(self) -> None:
        inventorymanager = unrealsdk.GetEngine().GamePlayers[0].Actor.GetPawnInventoryManager()
        for item in inventorymanager.BuyBackInventory:
            if item is None: 
                continue
            item.Mark = 1 # PlayerMark.PM_Standard

    def Enable(self) -> None:
        super().Enable()

    def Disable(self) -> None:
        super().Disable()
       
instance = CleaningUpPandora()
ModMenu.RegisterMod(instance)